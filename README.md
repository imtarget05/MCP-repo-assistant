# 🚀 MCP Repo Assistant: Enterprise GitHub Assistant & RAG Dashboard

**MCP Repo Assistant** là một trợ lý AI thông minh toàn diện dành cho việc phân tích, đọc hiểu và quản lý repository GitHub. Dự án được thiết kế theo chuẩn **Production-Grade**, tích hợp sâu các công nghệ tiên tiến nhất hiện nay trong lĩnh vực AI Engineering: **Model Context Protocol (MCP)**, **LangGraph**, **Hybrid RAG**, **Self-Correction Loops**, **Langfuse Tracing** và một giao diện **Glassmorphism Web Dashboard** trực quan hóa đồ thị thời gian thực vô cùng đẳng cấp.

Dự án này là minh chứng mạnh mẽ thể hiện kinh nghiệm thực tế về xây dựng hệ thống Multi-Agent, thiết kế luồng suy nghĩ phức tạp (Agent Orchestration), kiểm định chất lượng phản hồi, tối ưu hóa công cụ tìm kiếm vector và phát triển sản phẩm AI full-stack chất lượng cao để đưa vào CV.

---

## 🌟 Điểm Nhấn Công Nghệ & Tính Năng Nổi Bật (CV Highlights)

1. **Kiến Trúc Agentic Tự Sửa Lỗi (Self-Correction & Reflection Loop)**:
   - Thay vì trả lời thụ động hoặc dừng lại khi lỗi, hệ thống sử dụng sơ đồ tuần hoàn của **LangGraph**.
   - Node `verifier` sẽ phân tích sâu phản hồi từ `agent`. Nếu phát hiện nội dung trống, câu trả lời quá ngắn, lỗi công cụ chưa được xử lý, hoặc chứa comment giữ chỗ (`TODO`, `placeholder`), hệ thống sẽ sinh chỉ dẫn phản hồi chi tiết (Feedback) và định tuyến ngược lại Agent để tự chỉnh sửa (tối đa 3 lần).

2. **Giao Diện Dashboard Glassmorphism Đỉnh Cao (Wow-Factor UI)**:
   - Giao diện Single-Page Application (SPA) tuyệt đẹp được phục vụ trực tiếp từ **FastAPI** tại đường dẫn gốc `/`.
   - Thiết kế theo phong cách tối giản huyền bí (Futuristic Dark Theme) kết hợp neon highlights và bóng mờ `backdrop-filter` mượt mà.
   - Hỗ trợ stream phản hồi thời gian thực qua **Server-Sent Events (SSE)** cùng bộ parse Markdown mã nguồn chuyên nghiệp.

3. **Live LangGraph Trace Visualizer (Trực Quan Hóa Đồ Thị)**:
   - Giao diện tích hợp sơ đồ hoạt họa thể hiện trực tiếp luồng hoạt động của LangGraph (`Start` -> `Agent` -> `Tools` -> `Verifier` -> `End`).
   - Các Node và đường kết nối sẽ **tự động phát sáng và chuyển động** thời gian thực tương ứng với vị trí thực thi của Agent trên máy chủ.

4. **True Hybrid Search (Semantic + Keyword) Với Qdrant & FastEmbed**:
   - Sử dụng **OpenAI Embeddings** cho tìm kiếm ngữ nghĩa (Dense vector) kết hợp với **FastEmbed BM25** cho tìm kiếm từ khóa chính xác mã nguồn (Sparse vector).
   - Thiết lập cơ chế **Auto-Migration**: Hệ thống tự động phát hiện các vector collection cũ không tương thích và tự động tái tạo cấu trúc sang chuẩn Hybrid Search để tránh lỗi runtime.

5. **Giám Sát Hệ Thống Với Langfuse Tracing**:
   - Tích hợp chuẩn chỉ bộ Callback giám sát **Langfuse** giúp quản lý toàn bộ luồng gọi LLM, token tiêu thụ, prompt và độ trễ của công cụ, sẵn sàng đưa lên môi trường Cloud Production.

---

## 📐 Kiến Trúc Hệ Thống

```text
src/
  ├── agent/          # Điều phối LangGraph, self-correction, tracing & MCP bridge
  │     ├── assistant.py  # Định nghĩa Đồ thị (StateGraph) và bộ xác thực Verifier
  │     └── tools.py      # Cầu nối gọi các công cụ thông qua MCP client session
  │
  ├── mcp_server/     # MCP Server cung cấp GitHub & n8n tools chạy qua stdio
  │     └── server.py     # FastMCP server quản lý các API GitHub nâng cao
  │
  ├── rag/            # Tầng Ingestion & Retrieval của cơ sở dữ liệu vector
  │     ├── ingest.py     # Phân tách code bằng Language-Aware splitters
  │     └── retriever.py  # Cấu hình lai Hybrid Search (Dense + Sparse) trên Qdrant
  │
  └── api/            # API Service Layer (FastAPI) & Static Web Client
        ├── app.py        # Định nghĩa endpoints, SSE stream, CORS & mounts
        └── static/       # Single-Page Web Dashboard
              ├── index.html  # Cấu trúc giao diện 3 cột chuẩn SEO
              ├── index.css   # Style Glassmorphism & Neon animation
              └── app.js      # Điều khiển SSE stream & Live Graph Visualizer
```

---

## 🛠️ Hướng Dẫn Cài Đặt & Chạy Cục Bộ

### Yêu Cầu Hệ Thống
- Python 3.10+
- Một GitHub Personal Access Token (PAT)
- OpenAI API Key

### Các Bước Khởi Chạy

1. **Khởi tạo môi trường ảo và cài đặt thư viện**:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Cấu hình biến môi trường**:
   Sao chép `.env.example` thành `.env` và điền đầy đủ các thông tin:
   ```bash
   cp .env.example .env
   ```
   *Nội dung cấu hình:*
   ```env
   GITHUB_TOKEN=your_github_token_here
   OPENAI_API_KEY=your_openai_api_key_here
   
   # Tùy chọn nếu sử dụng Langfuse giám sát:
   LANGFUSE_PUBLIC_KEY=your_public_key
   LANGFUSE_SECRET_KEY=your_secret_key
   LANGFUSE_HOST=https://cloud.langfuse.com
   ```

3. **Chạy FastAPI Server**:
   ```bash
   PYTHONPATH=. uvicorn src.api.app:app --reload --port 8000
   ```

4. **Trải Nghiệm Hệ Thống**:
   Mở trình duyệt bất kỳ và truy cập địa chỉ: [http://localhost:8000](http://localhost:8000)

---

## 🐳 Triển Khai Nhanh Với Docker Compose

Dự án hỗ trợ container hóa toàn bộ stack (FastAPI API + Qdrant Vector Database) giúp chạy thử dễ dàng chỉ với một dòng lệnh:

```bash
docker-compose up --build
```

---

## 🧪 Kiểm Thử & Đánh Giá Chất Lượng

### Chạy Unit Test
Hệ thống sử dụng bộ mock LLM giúp chạy thử đồ thị LangGraph và API endpoint nhanh chóng mà không cần kết nối API thực tế:

```bash
PYTHONPATH=. pytest
```

### Đánh Giá Chất Lượng Phản Hồi RAGAS
Dự án tích hợp sẵn một pipeline đánh giá hiệu năng truy xuất tài liệu và chất lượng câu trả lời bằng bộ metric chuyên sâu của **RAGAS** (Faithfulness, Answer Relevancy, Context Recall, Context Precision):

```bash
PYTHONPATH=. python eval/evaluate.py
```
*Kết quả đánh giá sẽ được tự động xuất ra file `eval/results.csv` để trực quan hóa.*

---

## 📝 Cách Trình Bày Dự Án Này Vào CV Gây Ấn Tượng

**MCP Repo Assistant** | *AI Engineer / Full-Stack Developer*
- Thiết kế hệ thống trợ lý AI phân tích repository GitHub tự động bằng cách tích hợp **LangGraph**, **FastAPI** và **Model Context Protocol (MCP)** để giao tiếp thời gian thực với mã nguồn.
- Phát triển luồng suy nghĩ thông minh dạng **Self-Correction & Reflection Loop** thông qua LangGraph, giúp Agent tự động chỉnh sửa câu trả lời kém chất lượng tối đa 3 lần nhờ phản hồi của node `verifier`.
- Nâng cấp thành công cấu trúc truy xuất dữ liệu **Hybrid Search** (OpenAI Dense Embeddings + FastEmbed BM25 Sparse Vector) trên nền tảng **Qdrant Vector Database**, tự động hóa quá trình migration cơ sở dữ liệu.
- Thiết kế giao diện **Glassmorphism Web Dashboard** đỉnh cao, tích hợp **Live LangGraph Trace Visualizer** bằng SSE (Server-Sent Events) để trực quan hóa luồng đi của Agent thời gian thực.
- Triển khai giải pháp giám sát sản phẩm hoàn chỉnh với **Langfuse Tracing** và tối ưu hóa Docker Compose đa dịch vụ.
