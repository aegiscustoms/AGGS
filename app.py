import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import io

# --- 1. 초기 DB 및 관리자 설정 ---
def init_db():
    conn_auth = sqlite3.connect("users.db")
    admin_id = "aegis01210" 
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    conn_auth.commit()
    conn_auth.close()

init_db()

# --- 2. API 설정 (Secrets 확인) ---
if "GEMINI_KEY" not in st.secrets:
    st.error("❌ API 키가 없습니다. Streamlit Cloud Settings -> Secrets에 'GEMINI_KEY'를 등록하세요.")
    st.stop()

genai.configure(api_key=st.secrets["GEMINI_KEY"])
model = genai.GenerativeModel('gemini-2.0-flash')

# --- 3. 로그인 시스템 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    st.title("🔐 AEGIS 서비스 로그인")
    l_id = st.text_input("아이디")
    l_pw = st.text_input("비밀번호", type="password")
    if st.button("로그인"):
        conn = sqlite3.connect("users.db")
        res = conn.execute("SELECT is_approved, is_admin FROM users WHERE id=? AND pw=?", 
                           (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
        conn.close()
        if res:
            if res[0] == 1:
                st.session_state.logged_in = True
                st.session_state.user_id = l_id
                st.session_state.is_admin = bool(res[1])
                st.rerun()
            else: st.error("승인 대기 중입니다.")
        else: st.error("정보 불일치")
    st.stop()

# --- 4. 메인 기능 ---
st.sidebar.write(f"✅ 접속: {st.session_state.user_id}")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tab_names = ["🔍 HS검색", "📊 통계부호", "🌎 세계 HS/세율", "📜 FTA정보", "📦 화물통관진행정보", "🧮 세액계산기"]
if st.session_state.is_admin: tab_names.append("⚙️ 관리자")
tabs = st.tabs(tab_names)

# DB 상세 정보 표시 함수
def display_hsk_details(hsk_code, prob=""):
    code_clean = re.sub(r'[^0-9]', '', str(hsk_code))
    conn = sqlite3.connect("customs_master.db")
    m = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{code_clean}'", conn)
    r = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{code_clean}'", conn)
    req = pd.read_sql(f"SELECT law, agency, document FROM requirements WHERE hs_code = '{code_clean}'", conn)
    conn.close()
    if not m.empty:
        st.success(f"✅ [{code_clean}] {m['name_kr'].values[0]} {f'({prob})' if prob else ''}")
        c1, c2 = st.columns(2)
        with c1: st.write("**세율**"); st.table(r)
        with c2: st.write("**요건**"); st.table(req)

# [Tab 1] HS검색 (품명 기반 문구 제어 로직 반영)
with tabs[0]:
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("품명/물품정보 입력", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"], key="hs_i")
    
    if u_img: st.image(Image.open(u_img), caption="📸 분석 대상 이미지", width=300)

    if st.button("HS분석 실행", use_container_width=True):
        if u_img or u_input:
            with st.spinner("분석 중..."):
                try:
                    prompt = f"""당신은 전문 관세사입니다. 다음 규칙에 따라 HS코드를 제안하세요.

                    1. 품명: 유저입력('{u_input}')이 있으면 그대로 사용, 없으면 이미지를 보고 '예상품명' 제시.
                    2. 100% 확정 시: 10자리 HSK 코드 옆에 (100%) 표기. 이 경우 "불확실한 경우:" 섹션은 생략하세요.
                    3. 품명이 출력되거나 100% 확정된 결과가 있는 경우: "불확실한 경우:" 라는 문구 자체를 표시하지 마세요.
                    4. 미확정 시(불확실한 경우): '불확실한 경우:' 문구와 함께 6단위 기준 상위 3순위까지 확률(%) 추천.
                    결과 하단에 '추천결과: [코드] [확률]' 형식을 지켜주세요."""
                    
                    content = [prompt]
                    if u_img: content.append(Image.open(u_img))
                    if u_input: content.append(f"입력: {u_input}")
                    
                    res = model.generate_content(content)
                    st.markdown("### 📋 분석 리포트")
                    st.write(res.text)
                    
                    codes = re.findall(r'\d{10}', res.text)
                    if "100%" in res.text and codes:
                        st.divider()
                        display_hsk_details(codes[0], "100%")
                except Exception as e: st.error(f"오류: {e}")

# [Tab 2] 통계부호 (간소화)
with tabs[1]:
    s_q = st.text_input("", placeholder="부호 또는 명칭 입력")
    if st.button("검색"):
        conn = sqlite3.connect("customs_master.db")
        res = pd.read_sql(f"SELECT * FROM exemptions WHERE code LIKE '%{s_q}%' OR description LIKE '%{s_q}%'", conn)
        conn.close()
        st.table(res)

# [Tab 3] 세계 HS/세율
with tabs[2]:
    c_name = st.selectbox("국가", ["미국", "EU", "베트남", "중국", "일본"])
    raw_data = st.text_area("해외 사이트 데이터 복사")
    if st.button("분석 실행"):
        st.markdown(model.generate_content(f"{c_name} 관세 분석: {raw_data}").text)

# [기타 탭 및 하단 상담 채널]
with tabs[3]: st.info("📜 FTA 정보 수집 중...")
with tabs[4]: st.info("📦 화물통관진행정보 준비 중...")
with tabs[5]: st.write("🧮 세액계산기 영역")

st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com", use_container_width=True)
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/", use_container_width=True)
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn", use_container_width=True)