import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# main은 불러올 때 현재 폴더에 outputs를 만든다. 테스트는 임시 폴더에서 실행한다.
WORK_DIR = Path(tempfile.mkdtemp(prefix="hf-proxy-test-"))
os.chdir(WORK_DIR)
os.environ["GRADIO_DOWNLOAD_DIR"] = str(WORK_DIR / "downloads")
os.environ.pop("PUBLIC_BASE_URL", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class FakeClient:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def predict(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result() if callable(self.result) else self.result


@pytest.fixture
def api(monkeypatch):
    def use(result):
        fake = FakeClient(result)
        monkeypatch.setattr(main, "_client", fake)
        return fake

    return TestClient(main.app), use


def downloaded_image(name="image.webp", content=b"image-bytes"):
    folder = main.DOWNLOAD_DIR / "abc123"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(content)
    return path


def test_secret_file_outside_download_folder_is_not_published(api):
    client, use = api
    secret = WORK_DIR / ".env"
    secret.write_text("HF_TOKEN=hf_secret")
    use(str(secret))

    body = client.post("/api/generate", json={"prompt": "dog"}).json()

    assert body["status"] == "error"
    assert "image_url" not in body
    assert all("hf_secret" not in p.read_text(errors="ignore") for p in main.OUTPUT_DIR.iterdir())


def test_relative_path_to_server_file_is_rejected(api):
    client, use = api
    (WORK_DIR / "main_copy.py").write_text("print('server code')")
    use({"path": "main_copy.py"})

    assert client.post("/api/generate", json={"prompt": "dog"}).json()["status"] == "error"


def test_non_image_file_in_download_folder_is_rejected(api):
    client, use = api
    use(str(downloaded_image("notes.txt", b"text")))

    assert client.post("/api/generate", json={"prompt": "dog"}).json()["status"] == "error"


def test_downloaded_image_is_moved_and_served(api):
    client, use = api
    source = downloaded_image(content=b"webp-bytes")
    use([{"image": {"path": str(source)}}])

    body = client.post("/api/generate", json={"prompt": "dog"}).json()

    assert body["status"] == "success"
    assert body["image_url"].startswith("http://testserver/outputs/")
    assert body["image_url"].endswith(".webp")
    assert not source.exists()
    served = client.get(body["image_url"].replace("http://testserver", ""))
    assert served.status_code == 200
    assert served.content == b"webp-bytes"


def test_remote_url_is_returned_as_is(api):
    client, use = api
    use({"url": "https://example.com/result.png"})

    body = client.post("/api/generate", json={"prompt": "dog"}).json()

    assert body == {"status": "success", "image_url": "https://example.com/result.png", "raw_result": {"url": "https://example.com/result.png"}}


def test_public_base_url_is_used_when_set(api, monkeypatch):
    client, use = api
    monkeypatch.setattr(main, "PUBLIC_BASE_URL", "https://proxy.example.com")
    use(str(downloaded_image()))

    body = client.post("/api/generate", json={"prompt": "dog"}).json()

    assert body["image_url"].startswith("https://proxy.example.com/outputs/")


def test_gradio_array_is_passed_in_order(api):
    client, use = api
    fake = use("https://example.com/a.png")

    client.post("/api/generate", json={"data": ["crayon dog", "512", 640, "7.5", 42, "false"]})

    args, kwargs = fake.calls[0]
    assert args == ("crayon dog", 512, 640, 7.5, 42, False)
    assert kwargs == {"api_name": "/generate_image"}


@pytest.mark.parametrize("value, expected", [("false", False), ("False", False), ("0", False), (0, False), ("true", True), (1, True), (True, True)])
def test_randomize_seed_strings(value, expected):
    assert main.ImageRequest(data=["dog", 768, 1024, 8, 1, value]).randomize_seed is expected


@pytest.mark.parametrize("payload", [{}, {"prompt": ""}, {"data": ["dog", 768]}, {"data": ["dog", 768, 1024, 8, 1, "maybe"]}])
def test_invalid_requests_are_rejected(api, payload):
    client, use = api
    use("https://example.com/a.png")

    assert client.post("/api/generate", json=payload).status_code == 422


def test_expired_outputs_are_removed(monkeypatch):
    monkeypatch.setattr(main, "OUTPUT_TTL_SECONDS", 60)
    old = main.OUTPUT_DIR / "old.png"
    new = main.OUTPUT_DIR / "new.png"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    past = time.time() - 120
    os.utime(old, (past, past))

    main.remove_expired_outputs()

    assert not old.exists()
    assert new.exists()


def test_client_receives_token_and_download_folder(monkeypatch):
    created = {}

    class RecordingClient:
        def __init__(self, src, **kwargs):
            created["src"] = src
            created.update(kwargs)

    monkeypatch.setattr(main, "Client", RecordingClient)
    monkeypatch.setattr(main, "_client", None)
    monkeypatch.setattr(main, "HF_TOKEN", "hf_test")

    main.get_client()

    assert created == {"src": main.SPACE_ID, "token": "hf_test", "download_files": str(main.DOWNLOAD_DIR)}


def test_space_connection_error_is_reported(api, monkeypatch):
    client, _ = api

    def fail():
        raise ConnectionError("space is sleeping")

    monkeypatch.setattr(main, "_client", FakeClient(fail))

    body = client.post("/api/generate", json={"prompt": "dog"}).json()

    assert body == {"status": "error", "message": "space is sleeping"}