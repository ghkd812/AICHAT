import os
import io
import json
import re
import base64
from datetime import datetime
from html import unescape
from urllib.parse import quote
from urllib.request import Request, urlopen
import certifi

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from docx import Document
from openai import OpenAI
from pypdf import PdfReader
from pptx import Presentation
from pymongo import MongoClient
from pymongo.server_api import ServerApi

# ---------------------------------
# 기본 설정
# ---------------------------------
st.set_page_config(
    page_title="내 AI 챗봇",
    page_icon="🤖",
    layout="wide"
)

st.markdown("""
<style>
.block-container {
    padding-top: 1.5rem;
}
section[data-testid="stSidebar"] {
    width: 320px !important;
}
.chat-title {
    font-size: 2.2rem;
    font-weight: 800;
    margin-bottom: 1rem;
}
.preview-wrap {
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 10px;
    background: #fafafa;
    margin-top: 8px;
}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="chat-title">🤖 내 AI 챗봇</div>', unsafe_allow_html=True)

# ---------------------------------
# MongoDB
# ---------------------------------
@st.cache_resource
def get_db():
    mongo_uri = os.getenv("MONGODB_URI")
    mongo_db_name = os.getenv("MONGODB_DB")

    if not mongo_uri:
        try:
            mongo_uri = st.secrets["MONGODB_URI"]
        except Exception:
            mongo_uri = None

    if not mongo_db_name:
        try:
            mongo_db_name = st.secrets["MONGODB_DB"]
        except Exception:
            mongo_db_name = "my_ai_chatbot_prod"

    if not mongo_uri:
        st.error("MONGODB_URI가 없습니다. 환경변수 또는 Streamlit secrets에 설정하세요.")
        st.stop()

    client = MongoClient(
        mongo_uri,
        server_api=ServerApi("1"),
        tls=True,
        tlsCAFile=certifi.where(),
        connectTimeoutMS=20000,
        socketTimeoutMS=20000,
    )
    return client[mongo_db_name]

def get_chats_col():
    return get_db()["chats"]

def init_mongo():
    try:
        get_chats_col().create_index([("username", 1), ("chat_id", 1)], unique=True)
        get_chats_col().create_index([("username", 1), ("updated_at", -1)])
    except Exception as e:
        st.warning(f"MongoDB 인덱스 생성 경고: {e}")

init_mongo()

# ---------------------------------
# OpenAI
# ---------------------------------
api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
    except Exception:
        api_key = None

if not api_key:
    st.error("OPENAI_API_KEY가 없습니다. 환경변수 또는 Streamlit secrets에 설정하세요.")
    st.stop()

client = OpenAI(api_key=api_key)

def load_secret(name: str, default=None):
    value = os.getenv(name)
    if value:
        return value

    try:
        value = st.secrets[name]
        if value:
            return value
    except Exception:
        pass

    return default

NAVER_CLIENT_ID = load_secret("NAVER_SEARCH_CLIENT_ID")
NAVER_CLIENT_SECRET = load_secret("NAVER_SEARCH_CLIENT_SECRET")

# ---------------------------------
# 검색 기능
# ---------------------------------
def clean_naver_html(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", "", text)
    return unescape(cleaned).strip()

def search_naver(query: str, search_type: str = "news", display: int = 5):
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise RuntimeError(
            "네이버 검색을 사용하려면 NAVER_SEARCH_CLIENT_ID / NAVER_SEARCH_CLIENT_SECRET 설정이 필요합니다."
        )

    encoded_query = quote(query)
    url = (
        f"https://openapi.naver.com/v1/search/{search_type}.json"
        f"?query={encoded_query}&display={display}&sort=sim"
    )
    request = Request(url)
    request.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
    request.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)

    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    items = []
    for item in payload.get("items", []):
        items.append({
            "title": clean_naver_html(item.get("title", "")),
            "description": clean_naver_html(item.get("description", "")),
            "link": item.get("link", ""),
            "bloggername": item.get("bloggername", ""),
            "postdate": item.get("postdate", ""),
            "pubDate": item.get("pubDate", ""),
        })

    return {
        "query": query,
        "search_type": search_type,
        "total": payload.get("total", 0),
        "items": items,
    }

def format_naver_results_for_prompt(results: dict) -> str:
    if not results or not results.get("items"):
        return "검색 결과 없음"

    lines = [
        f"네이버 검색 타입: {results.get('search_type', '')}",
        f"검색어: {results.get('query', '')}",
    ]

    for idx, item in enumerate(results["items"], start=1):
        lines.append(f"[{idx}] 제목: {item.get('title', '')}")
        if item.get("description"):
            lines.append(f"설명: {item['description']}")
        if item.get("pubDate"):
            lines.append(f"발행일: {item['pubDate']}")
        if item.get("postdate"):
            lines.append(f"게시일: {item['postdate']}")
        if item.get("bloggername"):
            lines.append(f"작성자: {item['bloggername']}")
        if item.get("link"):
            lines.append(f"링크: {item['link']}")
        lines.append("")

    return "\n".join(lines).strip()

def render_naver_results(results: dict):
    if not results:
        return

    items = results.get("items", [])
    if not items:
        st.info("네이버 검색 결과가 없습니다.")
        return

    with st.expander("🔎 네이버 검색 결과", expanded=True):
        st.caption(
            f"검색어: {results.get('query', '')} / 타입: {results.get('search_type', '')} / 표시 결과: {len(items)}개"
        )
        for idx, item in enumerate(items, start=1):
            st.markdown(f"**{idx}. {item.get('title', '제목 없음')}**")
            meta = []
            if item.get("bloggername"):
                meta.append(item["bloggername"])
            if item.get("pubDate"):
                meta.append(item["pubDate"])
            if item.get("postdate"):
                meta.append(item["postdate"])
            if meta:
                st.caption(" / ".join(meta))
            if item.get("description"):
                st.write(item["description"])
            if item.get("link"):
                st.markdown(f"[원문 링크]({item['link']})")
            st.divider()

# ---------------------------------
# 로그인 관련
# ---------------------------------
def load_users():
    # 1순위: Streamlit secrets
    try:
        users = st.secrets.get("USERS", [])
        if isinstance(users, list) and len(users) > 0:
            return users
    except Exception:
        pass

    # 2순위: 로컬 users.json
    try:
        if os.path.exists("users.json"):
            with open("users.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception as e:
        st.warning(f"users.json 읽기 오류: {e}")

    return []

def verify_login(username: str, password: str) -> bool:
    users = load_users()
    username = str(username).strip()

    for user in users:
        if (
            str(user.get("username", "")).strip() == username
            and str(user.get("password", "")) == password
        ):
            return True
    return False

# ---------------------------------
# 파일 읽기 함수
# ---------------------------------
def read_pdf(file):
    try:
        file.seek(0)
        reader = PdfReader(file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except Exception as e:
        return f"[PDF 읽기 실패: {e}]"

def read_excel(file):
    try:
        file.seek(0)
        excel = pd.ExcelFile(file)
        text_parts = []
        previews = []

        for sheet_name in excel.sheet_names:
            df = pd.read_excel(excel, sheet_name=sheet_name)
            previews.append((sheet_name, df.head(20)))
            text_parts.append(f"[시트: {sheet_name}]")
            text_parts.append(df.head(50).to_string(index=False))

        return "\n\n".join(text_parts), previews
    except Exception as e:
        return f"[Excel 읽기 실패: {e}]", []

def read_csv(file):
    try:
        file.seek(0)
        df = pd.read_csv(file)
        return df.head(50).to_string(index=False), df.head(20)
    except Exception:
        try:
            file.seek(0)
            df = pd.read_csv(file, encoding="cp949")
            return df.head(50).to_string(index=False), df.head(20)
        except Exception as e:
            return f"[CSV 읽기 실패: {e}]", None

def read_ppt(file):
    try:
        file.seek(0)
        prs = Presentation(file)
        text = ""
        for i, slide in enumerate(prs.slides, start=1):
            slide_texts = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    value = shape.text.strip()
                    if value:
                        slide_texts.append(value)
            text += f"\n[슬라이드 {i}]\n" + "\n".join(slide_texts) + "\n"
        return text.strip()
    except Exception as e:
        return f"[PPT 읽기 실패: {e}]"

def read_docx(file):
    try:
        file.seek(0)
        doc = Document(file)
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    except Exception as e:
        return f"[DOCX 읽기 실패: {e}]"

def read_txt(file):
    file.seek(0)
    raw = file.getvalue()
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="ignore")

def image_to_base64(file):
    file.seek(0)
    return base64.b64encode(file.getvalue()).decode()

# ---------------------------------
# 엑셀 변환 / 구조화 데이터 추출
# ---------------------------------
def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name="result"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()

def extract_json_block(text: str):
    if not text:
        return None

    patterns = [
        r"```json\s*(.*?)\s*```",
        r"```[\w]*\s*(\[\s*{.*?}\s*\])\s*```",
        r"```[\w]*\s*(\{\s*.*?\s*\})\s*```",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            candidate = m.group(1).strip()
            try:
                return json.loads(candidate)
            except Exception:
                pass

    stripped = text.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except Exception:
            pass

    return None

def json_to_dataframe(data):
    if isinstance(data, list):
        if len(data) == 0:
            return pd.DataFrame()
        if all(isinstance(x, dict) for x in data):
            return pd.DataFrame(data)
        return pd.DataFrame({"value": data})

    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
                return pd.DataFrame(value)
        return pd.DataFrame([data])

    return None

def parse_markdown_table_to_df(text: str):
    if not text or "|" not in text:
        return None

    lines = [line.strip() for line in text.splitlines() if "|" in line]
    if len(lines) < 2:
        return None

    header_idx = None
    for i in range(len(lines) - 1):
        if re.fullmatch(r"\|?[\s:-|]+\|?", lines[i + 1]):
            header_idx = i
            break

    if header_idx is None:
        return None

    header_line = lines[header_idx]
    data_lines = lines[header_idx + 2:]

    headers = [h.strip() for h in header_line.strip("|").split("|")]
    rows = []

    for line in data_lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(cells)

    if not rows:
        return None

    return pd.DataFrame(rows, columns=headers)

def try_build_result_dataframe(full_text: str):
    data = extract_json_block(full_text)
    if data is not None:
        df = json_to_dataframe(data)
        if df is not None and not df.empty:
            return df

    df = parse_markdown_table_to_df(full_text)
    if df is not None and not df.empty:
        return df

    return None

# ---------------------------------
# HTML/CSS/JS 코드 추출 + 미리보기
# ---------------------------------
def extract_code_blocks(text: str):
    result = {
        "html": "",
        "css": "",
        "js": ""
    }

    if not text:
        return result

    matches = re.findall(r"```(\w+)?\s*(.*?)```", text, re.DOTALL)
    for lang, code in matches:
        lang = (lang or "").strip().lower()
        code = code.strip()

        if lang in ["html", "htm"]:
            result["html"] += "\n" + code
        elif lang == "css":
            result["css"] += "\n" + code
        elif lang in ["js", "javascript"]:
            result["js"] += "\n" + code

    return result

def build_preview_html_from_response(text: str):
    blocks = extract_code_blocks(text)

    html_code = blocks["html"].strip()
    css_code = blocks["css"].strip()
    js_code = blocks["js"].strip()

    if not html_code and not css_code and not js_code:
        return None, blocks

    if not html_code:
        return None, blocks

    if "<html" in html_code.lower():
        final_html = html_code

        if css_code:
            if "</head>" in final_html.lower():
                final_html = re.sub(
                    r"</head>",
                    f"<style>\n{css_code}\n</style>\n</head>",
                    final_html,
                    flags=re.IGNORECASE
                )
            else:
                final_html = f"<style>\n{css_code}\n</style>\n" + final_html

        if js_code:
            if "</body>" in final_html.lower():
                final_html = re.sub(
                    r"</body>",
                    f"<script>\n{js_code}\n</script>\n</body>",
                    final_html,
                    flags=re.IGNORECASE
                )
            else:
                final_html += f"\n<script>\n{js_code}\n</script>\n"

        return final_html, blocks

    final_html = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<style>
body {{
    font-family: Arial, sans-serif;
    padding: 20px;
    margin: 0;
    background: #ffffff;
}}
{css_code}
</style>
</head>
<body>
{html_code}
<script>
{js_code}
</script>
</body>
</html>
"""
    return final_html, blocks

def should_show_preview(user_input: str, response_text: str) -> bool:
    combined = f"{user_input}\n{response_text}".lower()

    keywords = [
        "html", "css", "js", "javascript",
        "퍼블리싱", "마크업", "웹페이지", "랜딩페이지",
        "코드", "미리보기", "화면 만들어", "ui 만들어"
    ]

    has_keyword = any(k in combined for k in keywords)
    has_html_block = "```html" in response_text.lower()

    return has_keyword or has_html_block

# ---------------------------------
# 대화 저장 함수 (MongoDB)
# ---------------------------------
def get_default_chat_data():
    return {
        "title": "새 대화",
        "messages": [
            {"role": "assistant", "content": "안녕하세요! 무엇을 도와드릴까요?"}
        ]
    }

def create_new_chat():
    chat_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    username = st.session_state.get("username", "guest")
    data = get_default_chat_data()

    get_chats_col().insert_one({
        "username": username,
        "chat_id": chat_id,
        "title": data["title"],
        "messages": data["messages"],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    })
    return chat_id

def load_chat(chat_id: str):
    username = st.session_state.get("username", "guest")
    doc = get_chats_col().find_one(
        {"username": username, "chat_id": chat_id},
        {"_id": 0, "title": 1, "messages": 1}
    )

    if doc:
        return {
            "title": doc.get("title", "새 대화"),
            "messages": doc.get("messages", get_default_chat_data()["messages"])
        }

    return get_default_chat_data()

def append_message(chat_id: str, role: str, content: str):
    username = st.session_state.get("username", "guest")

    get_chats_col().update_one(
        {"username": username, "chat_id": chat_id},
        {
            "$push": {
                "messages": {
                    "role": role,
                    "content": content
                }
            },
            "$set": {
                "updated_at": datetime.utcnow()
            },
            "$setOnInsert": {
                "created_at": datetime.utcnow(),
                "title": "새 대화"
            }
        },
        upsert=True
    )

def update_chat_title(chat_id: str, title: str):
    username = st.session_state.get("username", "guest")

    get_chats_col().update_one(
        {"username": username, "chat_id": chat_id},
        {
            "$set": {
                "title": title,
                "updated_at": datetime.utcnow()
            }
        }
    )

def list_chats():
    username = st.session_state.get("username", "guest")

    docs = list(
        get_chats_col()
        .find(
            {"username": username},
            {"_id": 0, "chat_id": 1, "title": 1, "updated_at": 1}
        )
        .sort("updated_at", -1)
    )

    result = []
    for doc in docs:
        result.append({
            "id": doc["chat_id"],
            "title": doc.get("title", "제목 없음")
        })
    return result

def delete_chat(chat_id: str):
    username = st.session_state.get("username", "guest")
    get_chats_col().delete_one({"username": username, "chat_id": chat_id})

def make_title_from_messages(messages):
    for msg in messages:
        if msg["role"] == "user":
            text = msg["content"].strip().replace("\n", " ")
            return text[:20] if len(text) > 20 else text
    return "새 대화"

# ---------------------------------
# 프롬프트
# ---------------------------------
def build_system_prompt(answer_length: str) -> str:
    if answer_length == "짧게":
        length_rule = "답변은 핵심만 2~3문장으로 간단히 설명한다."
    elif answer_length == "보통":
        length_rule = "답변은 3~6문장 정도로 설명한다."
    else:
        length_rule = "답변은 충분히 자세하게 설명하고, 필요하면 예시와 항목 정리를 포함한다."

    return f"""
너는 친절하고 유능한 한국어 AI 챗봇이다.
항상 한국어로 답변한다.
모르는 내용은 추측하지 말고 불확실하다고 말한다.
사용자가 파일을 첨부한 경우 첨부 내용을 우선 참고한다.
사용자가 네이버 검색 결과가 함께 제공되면 해당 검색 결과를 참고해서 최신 정보를 보완한다.
사용자가 이미지(여권, 비자, 신분증, 계약서, 문서 캡처 등)를 첨부하면 OCR 텍스트에 의존하지 말고 이미지 자체를 직접 판독해서 답변한다.

이미지에서 특히 아래 정보가 있으면 정리한다.
- 이름
- 여권번호
- 국적
- 생년월일
- 발급일
- 만료일
- 비자 종류
- 체류기간

생년월일, 발급일, 만료일은 가능하면 YYYY-MM-DD 형태로 정리한다.
확실하지 않은 값은 추정이라고 표시하거나 비워둘 수 있다.
이미지 속 텍스트가 흐리거나 일부 가려져 있으면 보이는 범위 내에서만 답변한다.
사용자가 표, 엑셀, 리스트, 정리본을 요청하면 가능하면 JSON 배열 또는 표 형태로 구조화해서 제공한다.

사용자가 HTML/CSS/JS 코드 또는 웹 화면 마크업을 요청하면:
- 가능하면 반드시 ```html``` / ```css``` / ```javascript``` 코드블록으로 나누어 제공한다.
- HTML은 바로 브라우저에서 렌더 가능한 형태로 작성한다.
- CSS가 있으면 별도 ```css``` 블록으로 준다.
- 필요한 경우 간단한 JS도 ```javascript``` 블록으로 준다.

{length_rule}
"""

# ---------------------------------
# 세션 초기화
# ---------------------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "username" not in st.session_state:
    st.session_state.username = None

if "uploaded_files_cache" not in st.session_state:
    st.session_state.uploaded_files_cache = []

if "answer_length" not in st.session_state:
    st.session_state.answer_length = "보통"

if "model_name" not in st.session_state:
    st.session_state.model_name = "gpt-4.1-mini"

if "last_result_df" not in st.session_state:
    st.session_state.last_result_df = None

if "last_preview_html" not in st.session_state:
    st.session_state.last_preview_html = None

if "last_preview_blocks" not in st.session_state:
    st.session_state.last_preview_blocks = {"html": "", "css": "", "js": ""}

if "search_mode" not in st.session_state:
    st.session_state.search_mode = "기본 AI"

if "naver_search_type" not in st.session_state:
    st.session_state.naver_search_type = "news"

# ---------------------------------
# 로그인 화면
# ---------------------------------
if not st.session_state.logged_in:
    st.subheader("🔐 로그인")

    login_username = st.text_input("아이디")
    login_password = st.text_input("비밀번호", type="password")

    if st.button("로그인", use_container_width=True):
        if verify_login(login_username, login_password):
            st.session_state.logged_in = True
            st.session_state.username = login_username
            st.success("로그인되었습니다.")
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호가 올바르지 않습니다.")

    st.info("Streamlit Secrets에 USERS 계정을 등록해두면 됩니다.")
    st.stop()

# ---------------------------------
# 로그인 후 현재 대화 초기화
# ---------------------------------
if "current_chat_id" not in st.session_state:
    chats = list_chats()
    if chats:
        st.session_state.current_chat_id = chats[0]["id"]
    else:
        st.session_state.current_chat_id = create_new_chat()

# ---------------------------------
# 사이드바
# ---------------------------------
with st.sidebar:
    st.write(f"로그인 사용자: **{st.session_state.username}**")

    if st.button("로그아웃", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.uploaded_files_cache = []
        st.session_state.last_result_df = None
        st.session_state.last_preview_html = None
        st.session_state.last_preview_blocks = {"html": "", "css": "", "js": ""}
        if "current_chat_id" in st.session_state:
            del st.session_state["current_chat_id"]
        st.rerun()

    st.divider()
    st.header("대화")

    if st.button("＋ 새 대화", use_container_width=True):
        st.session_state.current_chat_id = create_new_chat()
        st.session_state.uploaded_files_cache = []
        st.session_state.last_result_df = None
        st.session_state.last_preview_html = None
        st.session_state.last_preview_blocks = {"html": "", "css": "", "js": ""}
        st.rerun()

    st.divider()

    for chat in list_chats():
        col1, col2 = st.columns([4, 1])

        with col1:
            if st.button(chat["title"], key=f"open_{chat['id']}", use_container_width=True):
                st.session_state.current_chat_id = chat["id"]
                st.session_state.uploaded_files_cache = []
                st.session_state.last_result_df = None
                st.session_state.last_preview_html = None
                st.session_state.last_preview_blocks = {"html": "", "css": "", "js": ""}
                st.rerun()

        with col2:
            if st.button("🗑", key=f"del_{chat['id']}", use_container_width=True):
                deleting_current = (st.session_state.current_chat_id == chat["id"])
                delete_chat(chat["id"])
                remaining = list_chats()
                if deleting_current:
                    if remaining:
                        st.session_state.current_chat_id = remaining[0]["id"]
                    else:
                        st.session_state.current_chat_id = create_new_chat()
                st.rerun()

    st.divider()
    st.header("답변 설정")

    model_options = ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-5.4"]
    if st.session_state.model_name not in model_options:
        st.session_state.model_name = "gpt-4.1-mini"

    st.session_state.model_name = st.selectbox(
        "모델",
        model_options,
        index=model_options.index(st.session_state.model_name)
    )

    length_options = ["짧게", "보통", "자세히"]
    if st.session_state.answer_length not in length_options:
        st.session_state.answer_length = "보통"

    st.session_state.answer_length = st.selectbox(
        "답변 길이",
        length_options,
        index=length_options.index(st.session_state.answer_length)
    )

    search_mode_options = ["기본 AI", "OpenAI 웹 검색", "네이버 검색 + AI", "네이버 + OpenAI 웹 검색"]
    if st.session_state.search_mode not in search_mode_options:
        st.session_state.search_mode = "기본 AI"

    st.session_state.search_mode = st.selectbox(
        "검색 모드",
        search_mode_options,
        index=search_mode_options.index(st.session_state.search_mode),
        help="기본 답변만 할지, OpenAI 웹 검색 또는 네이버 검색 결과를 함께 사용할지 선택합니다."
    )

    naver_search_options = ["news", "webkr", "blog"]
    if st.session_state.naver_search_type not in naver_search_options:
        st.session_state.naver_search_type = "news"

    st.session_state.naver_search_type = st.selectbox(
        "네이버 검색 타입",
        naver_search_options,
        index=naver_search_options.index(st.session_state.naver_search_type),
        help="네이버 Open API 검색 대상입니다. news=뉴스, webkr=웹문서, blog=블로그"
    )

    if "네이버" in st.session_state.search_mode and (not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET):
        st.warning("네이버 검색을 쓰려면 NAVER_SEARCH_CLIENT_ID / NAVER_SEARCH_CLIENT_SECRET 설정이 필요합니다.")

# ---------------------------------
# 현재 대화 로드
# ---------------------------------
current_data = load_chat(st.session_state.current_chat_id)
messages = current_data["messages"]

# ---------------------------------
# 파일 업로드
# ---------------------------------
st.subheader("📎 파일 첨부")

uploaded_files = st.file_uploader(
    "여기에 파일을 드래그하거나 클릭해서 선택하세요",
    type=[
        "pdf", "xlsx", "xls", "csv",
        "pptx", "docx", "txt",
        "png", "jpg", "jpeg", "webp"
    ],
    accept_multiple_files=True,
    key="main_file_uploader"
)

if uploaded_files is not None and len(uploaded_files) > 0:
    st.session_state.uploaded_files_cache = uploaded_files

active_files = st.session_state.uploaded_files_cache

file_context = ""
image_inputs = []

if active_files:
    st.success(f"{len(active_files)}개 파일 업로드됨")

    for f in active_files:
        ext = f.name.split(".")[-1].lower()
        st.write("첨부됨:", f.name)

        try:
            if ext == "pdf":
                text = read_pdf(f)
                file_context += f"\n\n[PDF: {f.name}]\n{text}"

            elif ext in ["xlsx", "xls"]:
                excel_text, previews = read_excel(f)
                file_context += f"\n\n[EXCEL: {f.name}]\n{excel_text}"
                for sheet_name, df in previews:
                    with st.expander(f"미리보기: {f.name} / {sheet_name}", expanded=False):
                        st.dataframe(df, use_container_width=True)

            elif ext == "csv":
                csv_text, preview_df = read_csv(f)
                file_context += f"\n\n[CSV: {f.name}]\n{csv_text}"
                if preview_df is not None:
                    with st.expander(f"미리보기: {f.name}", expanded=False):
                        st.dataframe(preview_df, use_container_width=True)

            elif ext == "pptx":
                text = read_ppt(f)
                file_context += f"\n\n[PPTX: {f.name}]\n{text}"

            elif ext == "docx":
                text = read_docx(f)
                file_context += f"\n\n[DOCX: {f.name}]\n{text}"

            elif ext == "txt":
                text = read_txt(f)
                file_context += f"\n\n[TXT: {f.name}]\n{text}"

            elif ext in ["png", "jpg", "jpeg", "webp"]:
                with st.expander(f"이미지 미리보기: {f.name}", expanded=False):
                    st.image(f, caption=f"{f.name} 원본", use_container_width=True)

                file_context += f"""
[이미지 파일: {f.name}]
이 이미지는 사용자가 첨부한 원본 이미지입니다.
OCR 전처리 텍스트는 제공하지 않으니, 필요한 경우 이미지 자체를 직접 분석하세요.
여권, 비자, 신분증, 문서 이미지, 캡처 화면일 수 있으므로
이름, 여권번호, 국적, 생년월일, 발급일, 만료일, 비자 종류, 체류기간 등의 정보가 보이면 정리하세요.
"""

                image_inputs.append({
                    "type": "input_image",
                    "image_url": f"data:{f.type};base64,{image_to_base64(f)}"
                })

        except Exception as e:
            st.error(f"{f.name} 처리 중 오류: {e}")

    if st.button("첨부 파일 비우기"):
        st.session_state.uploaded_files_cache = []
        st.rerun()
else:
    st.info("업로드된 파일 없음")

with st.expander("첨부 데이터 확인", expanded=False):
    st.write("file_context 길이:", len(file_context))
    st.write("image_inputs 개수:", len(image_inputs))

# ---------------------------------
# 이전 대화 출력
# ---------------------------------
for msg in messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# ---------------------------------
# 마지막 HTML 미리보기 재표시
# ---------------------------------
if st.session_state.last_preview_html:
    st.subheader("🖥 HTML/CSS 미리보기")
    components.html(st.session_state.last_preview_html, height=700, scrolling=True)

    with st.expander("미리보기 코드 보기", expanded=False):
        blocks = st.session_state.last_preview_blocks

        if blocks.get("html"):
            st.markdown("**HTML**")
            st.code(blocks["html"], language="html")

        if blocks.get("css"):
            st.markdown("**CSS**")
            st.code(blocks["css"], language="css")

        if blocks.get("js"):
            st.markdown("**JavaScript**")
            st.code(blocks["js"], language="javascript")

# ---------------------------------
# 사용자 입력
# ---------------------------------
user_input = st.chat_input("메시지를 입력하세요")

if user_input:
    chat_id = st.session_state.current_chat_id

    messages.append({"role": "user", "content": user_input})

    if current_data.get("title") in ["새 대화", "제목 없음"]:
        new_title = make_title_from_messages(messages)
        current_data["title"] = new_title
        update_chat_title(chat_id, new_title)

    append_message(chat_id, "user", user_input)

    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_text = ""

        try:
            history_for_model = []
            for msg in messages[:-1]:
                history_for_model.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

            search_mode = st.session_state.search_mode
            use_openai_web_search = search_mode in ["OpenAI 웹 검색", "네이버 + OpenAI 웹 검색"]
            use_naver_search = search_mode in ["네이버 검색 + AI", "네이버 + OpenAI 웹 검색"]

            naver_results = None
            naver_prompt_context = "사용 안 함"

            if use_naver_search:
                naver_results = search_naver(
                    user_input,
                    search_type=st.session_state.naver_search_type,
                    display=5
                )
                naver_prompt_context = format_naver_results_for_prompt(naver_results)
                render_naver_results(naver_results)

            user_content = [
                {
                    "type": "input_text",
                    "text": f"""사용자 질문:
{user_input}

첨부 파일 내용:
{file_context if file_context else "첨부된 파일 없음"}

네이버 검색 결과:
{naver_prompt_context}
"""
                }
            ]

            if image_inputs:
                user_content.extend(image_inputs)

            request_kwargs = {
                "model": st.session_state.model_name,
                "input": [
                    {"role": "system", "content": build_system_prompt(st.session_state.answer_length)},
                    *history_for_model,
                    {"role": "user", "content": user_content}
                ],
                "stream": True,
            }

            if use_openai_web_search:
                request_kwargs["tools"] = [
                    {
                        "type": "web_search_preview",
                        "search_context_size": "medium",
                        "user_location": {
                            "type": "approximate",
                            "country": "KR",
                            "timezone": "Asia/Seoul",
                        },
                    }
                ]

            stream = client.responses.create(**request_kwargs)

            for event in stream:
                if event.type == "response.output_text.delta":
                    full_text += event.delta
                    placeholder.markdown(full_text + "▌")
                elif event.type == "response.completed":
                    break

            placeholder.markdown(full_text)

        except Exception as e:
            full_text = f"오류가 발생했습니다: {e}"
            placeholder.error(full_text)

        messages.append({"role": "assistant", "content": full_text})
        append_message(chat_id, "assistant", full_text)

        result_df = try_build_result_dataframe(full_text)
        st.session_state.last_result_df = result_df

        if result_df is not None and not result_df.empty:
            st.subheader("📊 AI 결과 표")
            st.dataframe(result_df, use_container_width=True)

            result_excel = dataframe_to_excel_bytes(result_df, sheet_name="ai_result")
            st.download_button(
                label="📥 AI 결과 Excel 다운로드",
                data=result_excel,
                file_name="ai_result.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"download_ai_excel_{st.session_state.current_chat_id}"
            )

        st.session_state.last_preview_html = None
        st.session_state.last_preview_blocks = {"html": "", "css": "", "js": ""}

        if should_show_preview(user_input, full_text):
            preview_html, preview_blocks = build_preview_html_from_response(full_text)

            if preview_html:
                st.session_state.last_preview_html = preview_html
                st.session_state.last_preview_blocks = preview_blocks

                st.subheader("🖥 HTML/CSS 미리보기")
                components.html(preview_html, height=700, scrolling=True)

                with st.expander("미리보기 코드 보기", expanded=False):
                    if preview_blocks.get("html"):
                        st.markdown("**HTML**")
                        st.code(preview_blocks["html"], language="html")

                    if preview_blocks.get("css"):
                        st.markdown("**CSS**")
                        st.code(preview_blocks["css"], language="css")

                    if preview_blocks.get("js"):
                        st.markdown("**JavaScript**")
                        st.code(preview_blocks["js"], language="javascript")
            else:
                if "```css" in full_text.lower() and "```html" not in full_text.lower():
                    st.info("CSS 코드만 있어서 미리보기는 생략했습니다. HTML 코드까지 같이 있으면 바로 렌더됩니다.")
