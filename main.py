import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from gradio_client import Client
from pydantic import BaseModel, Field, model_validator


load_dotenv()

SPACE_ID = os.getenv("SPACE_ID", "mrfakename/z-image-turbo")
HF_TOKEN = os.getenv("HF_TOKEN") or None
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

# gradio_client가 Space 결과 파일을 내려받는 폴더. 로컬 파일은 이 폴더 안의 것만 공개한다.
DOWNLOAD_DIR = Path(os.getenv("GRADIO_DOWNLOAD_DIR", "downloads")).resolve()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 배포 환경에서 리버스 프록시 뒤에 있으면 request.url_for가 http 주소를 만들 수 있어 공개 주소를 따로 받는다.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# 공개 폴더의 생성 파일은 이 시간이 지나면 지운다. 0이면 지우지 않는다.
OUTPUT_TTL_SECONDS = int(os.getenv("OUTPUT_TTL_SECONDS", "86400"))

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

app = FastAPI(title="Ennoia Hugging Face Proxy API")
app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")

_client: Client | None = None


def get_client() -> Client:
    """첫 요청에서 Space에 연결한다. 모듈을 불러올 때 연결하면 Space가 잠시 내려가 있을 때 서버가 시작되지 않는다."""
    global _client
    if _client is None:
        # gradio_client 1.0부터 인자 이름이 hf_token에서 token으로 바뀌었다.
        _client = Client(SPACE_ID, token=HF_TOKEN, download_files=str(DOWNLOAD_DIR))
    return _client


def parse_bool(value: Any) -> bool:
    """bool("false")는 True라서 문자열은 따로 해석한다."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "y"):
            return True
        if text in ("false", "0", "no", "n", ""):
            return False
    raise ValueError(f"randomize_seed must be a boolean: {value!r}")


class ImageRequest(BaseModel):
    prompt: str | None = Field(default=None, min_length=1)
    seed: int = 0
    width: int = 768
    height: int = 1024
    guidance_scale: float = 8
    randomize_seed: bool = False
    data: list[Any] | None = None

    @model_validator(mode="after")
    def normalize_gradio_data(self) -> "ImageRequest":
        if self.data:
            if len(self.data) < 6:
                raise ValueError("data must contain prompt, width, height, guidance_scale, seed, randomize_seed")
            self.prompt = str(self.data[0])
            self.width = int(self.data[1])
            self.height = int(self.data[2])
            self.guidance_scale = float(self.data[3])
            self.seed = int(self.data[4])
            self.randomize_seed = parse_bool(self.data[5])

        if not self.prompt:
            raise ValueError("prompt is required")

        return self


def downloaded_image_path(value: str) -> Path | None:
    """Space가 돌려준 문자열이 내려받은 이미지 파일을 가리킬 때만 경로를 돌려준다.

    응답 문자열을 그대로 믿으면 .env처럼 서버에 있는 다른 파일도 공개 폴더로 복사될 수 있다.
    """
    try:
        path = Path(value).resolve()
    except (OSError, ValueError):
        return None

    if not path.is_relative_to(DOWNLOAD_DIR):
        return None
    if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
        return None
    return path


def find_image_value(value: Any) -> str | None:
    """Find the first likely image URL or downloaded image file in a Gradio result."""
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return value
        if downloaded_image_path(value):
            return value
        return None

    if isinstance(value, dict):
        for key in ("url", "path", "name", "file", "image"):
            if key in value:
                found = find_image_value(value[key])
                if found:
                    return found
        for nested in value.values():
            found = find_image_value(nested)
            if found:
                return found

    if isinstance(value, (list, tuple)):
        for item in value:
            found = find_image_value(item)
            if found:
                return found

    return None


def remove_expired_outputs(now: float | None = None) -> None:
    if OUTPUT_TTL_SECONDS <= 0:
        return

    deadline = (now if now is not None else time.time()) - OUTPUT_TTL_SECONDS
    for path in OUTPUT_DIR.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < deadline:
                path.unlink()
        except OSError:
            # 다른 요청이 같은 파일을 읽거나 지우는 중이면 다음 정리 때 다시 확인한다.
            continue


def public_output_url(filename: str, request: Request) -> str:
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}/outputs/{filename}"
    return str(request.url_for("outputs", path=filename))


def to_public_image_url(image_value: str, request: Request) -> str:
    if image_value.startswith(("http://", "https://")):
        return image_value

    source = downloaded_image_path(image_value)
    if source is None:
        raise ValueError("The image file is not inside the Gradio download folder.")

    filename = f"{uuid.uuid4().hex}{source.suffix.lower()}"
    # 내려받은 파일은 공개 폴더로 옮긴다. 복사하면 같은 이미지가 두 곳에 계속 쌓인다.
    shutil.move(str(source), OUTPUT_DIR / filename)
    return public_output_url(filename, request)


@app.get("/")
def health() -> dict[str, str]:
    return {"status": "ok", "space_id": SPACE_ID}


@app.post("/api/generate")
def generate(req: ImageRequest, request: Request) -> dict[str, Any]:
    remove_expired_outputs()

    try:
        result = get_client().predict(
            req.prompt,
            req.width,
            req.height,
            req.guidance_scale,
            req.seed,
            req.randomize_seed,
            api_name="/generate_image",
        )

        image_value = find_image_value(result)
        if not image_value:
            return {
                "status": "error",
                "message": "No image URL or file path was found in the Hugging Face response.",
                "raw_result": result,
            }

        return {
            "status": "success",
            "image_url": to_public_image_url(image_value, request),
            "raw_result": result,
        }

    except Exception as exc:
        return {
            "status": "error",
            "message": str(exc),
        }