"""python -m chunking.webui：启动预览服务（默认 127.0.0.1:8765）。"""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "chunking.webui.app:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
    )


if __name__ == "__main__":
    main()
