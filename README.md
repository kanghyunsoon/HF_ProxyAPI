# Ennoia Hugging Face Proxy API

Ennoia에서 Hugging Face Gradio Space를 직접 호출하기 어렵기 때문에, 이 서버가 중간에서 이미지 생성을 완료한 뒤 깔끔한 JSON만 반환합니다.

## 구조

```text
Ennoia -> POST /api/generate -> FastAPI Proxy -> Hugging Face Space
Ennoia <- {"status":"success","image_url":"..."}
```

## 로컬 실행

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

브라우저에서 확인:

```text
http://127.0.0.1:8000/
```

테스트 요청:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/generate" `
  -ContentType "application/json" `
  -Body '{"prompt":"a cinematic portrait photo of a silver robot, studio lighting","seed":1234}'
```

## 환경 변수

이 프로젝트는 토큰을 코드에 하드코딩하지 않습니다. `main.py`는 아래처럼 환경 변수에서 값을 읽습니다.

```python
SPACE_ID = os.getenv("SPACE_ID", "mrfakename/z-image-turbo")
HF_TOKEN = os.getenv("HF_TOKEN")
```

기본 Space ID:

```text
SPACE_ID=mrfakename/z-image-turbo
```

비공개 Hugging Face Space를 쓰거나 인증이 필요한 경우에만 `HF_TOKEN`을 설정하세요.

```text
HF_TOKEN=your_hugging_face_token
```

## 로컬 환경 변수 설정

로컬에서 테스트할 때는 `.env.example`을 참고해서 `.env` 파일을 만들 수 있습니다.

```powershell
Copy-Item .env.example .env
```

그 다음 `.env`에 실제 값을 넣습니다.

```text
SPACE_ID=mrfakename/z-image-turbo
HF_TOKEN=your_hugging_face_token
```

주의: `.env`는 `.gitignore`에 포함되어 있으므로 GitHub에 올리지 않습니다. `.env.example`에는 진짜 토큰을 넣지 마세요.

## Render 배포

1. GitHub에 이 프로젝트를 업로드합니다.
2. Render에서 `New` -> `Web Service`를 선택합니다.
3. GitHub 저장소를 연결합니다.
4. 아래처럼 설정합니다.

```text
Runtime: Python
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
```

5. Render의 서비스 설정에서 `Environment` 탭을 엽니다.
6. 필요한 환경 변수를 추가합니다.

```text
Key: SPACE_ID
Value: mrfakename/z-image-turbo
```

비공개 Space나 인증이 필요한 경우에는 추가로 입력합니다.

```text
Key: HF_TOKEN
Value: 여기에 실제 Hugging Face 토큰 입력
```

7. `Save Changes`를 누르면 Render가 다시 배포하면서 환경 변수를 서버에 주입합니다.

배포 URL 예시:

```text
https://your-service-name.onrender.com
```

## Ennoia 요청 설정

Method:

```text
POST
```

URL:

```text
https://your-service-name.onrender.com/api/generate
```

Headers:

```text
Content-Type: application/json
```

Body:

```json
{
  "prompt": "your prompt here",
  "seed": 1234
}
```

또는 Hugging Face Gradio 원본 형태처럼 `data` 배열로 보낼 수 있습니다.

```json
{
  "data": [
    "your prompt here",
    768,
    1024,
    8,
    0,
    false
  ]
}
```

응답에서 사용할 값:

```text
image_url
```

## 주의

Render 무료 서버는 일정 시간 요청이 없으면 잠자기 상태가 됩니다. 첫 요청은 느릴 수 있습니다.
