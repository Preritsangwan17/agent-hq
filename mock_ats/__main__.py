import uvicorn

from mock_ats.app import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8799, log_level="warning")
