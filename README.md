# Ennoia Hugging Face Proxy API

엔노이아에서 Hugging Face Gradio Space를 직접 호출하기 어렵기 때문에, 이 서버가 중간에서 이미지 생성을 완료한 뒤 깔끔한 JSON만 반환합니다.

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

## Render 배포

1. GitHub에 새 저장소를 만듭니다.
2. 이 폴더의 파일을 GitHub 저장소에 업로드합니다.
3. Render에서 `New` -> `Web Service`를 선택합니다.
4. GitHub 저장소를 연결합니다.
5. 설정값을 아래처럼 입력합니다.

```text
Runtime: Python
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
```

6. 배포가 끝나면 Render URL이 생깁니다.

예시:

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

또는 Hugging Face Gradio 원본 형태처럼 `data` 배열로 보내도 됩니다.

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

## 환경변수

기본 Space는 아래 값입니다.

```text
SPACE_ID=mrfakename/z-image-turbo
```

다른 Hugging Face Space를 쓰려면 Render의 Environment Variables에 `SPACE_ID`를 추가하세요.

비공개 Space를 쓰는 경우에는 Hugging Face 토큰을 추가하세요.

```text
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## 주의

Render 무료 서버는 일정 시간 요청이 없으면 잠자기 상태가 됩니다. 첫 요청은 느릴 수 있습니다.
