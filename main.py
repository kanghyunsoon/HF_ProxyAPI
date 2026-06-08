import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from gradio_client import Client
from pydantic import BaseModel, Field, model_validator


SPACE_ID = os.getenv("SPACE_ID", "mrfakename/z-image-turbo")
HF_TOKEN = os.getenv("HF_TOKEN")
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Ennoia Hugging Face Proxy API")
app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")

client = Client(SPACE_ID, hf_token=HF_TOKEN) if HF_TOKEN else Client(SPACE_ID)


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
            self.randomize_seed = bool(self.data[5])

        if not self.prompt:
            raise ValueError("prompt is required")

        return self


def find_image_value(value: Any) -> str | None:
    """Find the first likely image URL or local file path in a Gradio result."""
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return value
        if Path(value).exists():
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


def to_public_image_url(image_value: str, request: Request) -> str:
    if image_value.startswith(("http://", "https://")):
        return image_value

    source = Path(image_value)
    suffix = source.suffix or ".png"
    filename = f"{uuid.uuid4().hex}{suffix}"
    destination = OUTPUT_DIR / filename
    shutil.copyfile(source, destination)
    return str(request.url_for("outputs", path=filename))


@app.get("/")
def health() -> dict[str, str]:
    return {"status": "ok", "space_id": SPACE_ID}


@app.post("/api/generate")
def generate(req: ImageRequest, request: Request) -> dict[str, Any]:
    try:
        result = client.predict(
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
