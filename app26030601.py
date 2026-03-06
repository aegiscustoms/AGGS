import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import requests
import xml.etree.ElementTree as ET

# --- 전역 설정 및 폰트 사양 ---
TITLE_FONT_SIZE = "15px"
CONTENT_FONT_SIZE = "12px"
# 관세청 서버의 봇 인식 차단을 방지하기 위한 헤더
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/xml"
}

# --- 1. 초기 DB 설정 ---
def init_db():
    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, name, is_approved, is_admin) VALUES (?, ?, ?, 1, 1)", 
                      ("aegis01210", admin_pw, "관리자"))
    conn_auth.commit()
    conn_auth.close()

init_db()

# Gemini API 설정
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 세션 관리 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    st.title("🔐 AEGIS 서비스 로그인")
    l_id = st.text_input("아이디")
    l_pw = st.text_input("비밀번호", type="password")
    if st.button("로그인"):
        conn = sqlite3.connect("users.db")
        res = conn.execute("SELECT is_approved, is_admin, name FROM users WHERE id=? AND pw=?", 
                           (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
        conn.close()
        if res and res[0] == 1:
            st.session_state.logged_in = True
            st.session_state.user_id = l_id
            st.session_state.user_name = res[2]
            st.session_state.is_admin = bool(res[1])
            st.rerun()
        else: st.error("승인 대기 또는 정보 불일치")
    st.stop()

# --- 3. 메인 화면 ---
st.sidebar.write(f"✅ {st.session_state.user_name} 접속 중")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관진행정보", "🧮 세액계산기"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 (관세사님 요청 로직 고정) ---
with tabs[0]:
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("품명/물품정보(용도/기능/성분/재질) 입력", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"], key="hs_i")
    if u_img: st.image(Image.open(u_img), caption="📸 분석 대상 이미지", width=300)
    if st.button("HS분석 실행", use_container_width=True):
        if u_img or u_input:
            with st.spinner("AI 분석 중..."):
                try:
                    prompt = f"""당신은 전문 관세사입니다. 아래 지침에 따라 HS코드를 분류하고 리포트를 작성하세요.
                    1. 품명: (유저입력 '{u_input}' 참고하여 예상 품명 제시)
                    2. 추천결과:
                       - 1순위가 100%인 경우: "1순위 [코드] 100%"만 출력하고 종료.
                       - 미확정인 경우: 상위 3순위까지 추천하되 3순위가 낮으면 2순위까지만.
                       - 형식: "n순위 [코드] [확률]%" """
                    content = [prompt]
                    if u_img: content.append(Image.open(u_img))
                    if u_input: content.append(f"상세 정보: {u_input}")
                    res = model.generate_content(content)
                    st.markdown("### 📋 분석 리포트")
                    st.write(res.text)
                except Exception as e: st.error(f"오류: {e}")

# --- [Tab 2] HS정보 (가이드 API018 정밀 반영) ---
with tabs[1]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📘 실시간 HS부호 및 세율 (Uni-Pass)</div>", unsafe_allow_html=True)
    RATE_KEY = st.secrets.get("RATE_API_KEY", "").strip()
    target_hs = st.text_input("HS코드 10자리 입력", placeholder="예: 0302440000", key="hs_rate_api")
    if st.button("실시간 HS 정보 조회", use_container_width=True):
        if target_hs:
            with st.spinner("데이터 조회 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/hsSgnQry/searchHsSgn"
                params = {"crkyCn": RATE_KEY, "hsSgn": target_hs.strip(), "koenTp": "1"}
                try:
                    res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
                    root = ET.fromstring(res.content)
                    # 가이드북 태그명(korePrnm, txrt) 직접 추출
                    k_name = root.findtext(".//korePrnm")
                    if k_name:
                        st.info(f"✅ 한글품명: {k_name}")
                        st.write(f"영문품명: {root.findtext('.//englPrnm')}")
                        st.success(f"적용세율: {root.findtext('.//txrt') or '정보없음'}")
                    else: st.warning("정보를 찾을 수 없습니다. 인증키 승인 여부 및 HS코드를 확인하세요.")
                except Exception as e: st.error(f"연결 오류: {e}")

# --- [Tab 3] 통계부호 (가이드 API019 정밀 반영) ---
with tabs[2]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📊 실시간 통계부호 검색 (Uni-Pass)</div>", unsafe_allow_html=True)
    STAT_KEY = st.secrets.get("STAT_API_KEY", "").strip()
    # 가이드북 기반 통계부호구분코드 매핑
    clft_dict = {"관세감면/분납": "A01", "내국세율": "A04", "용도부호": "A05", "보세구역": "A08"}
    col1, col2 = st.columns([1, 2])
    with col1: sel_clft = st.selectbox("구분 선택", list(clft_dict.keys()))
    with col2: kw = st.text_input("키워드(한글내역)", placeholder="예: 정밀전자")
    if st.button("부호 실시간 검색", use_container_width=True):
        with st.spinner("코드 서버 조회 중..."):
            url = "https://unipass.customs.go.kr:38010/ext/rest/statsSgnQry/retrieveStatsSgnBrkd"
            params = {"crkyCn": STAT_KEY, "statsSgnclftCd": clft_dict[sel_clft]}
            try:
                res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
                root = ET.fromstring(res.content)
                # 가이드북 태그명 statsSgnQryVo 하위의 statsSgn, koreBrkd 추출
                codes = root.findall(".//statsSgnQryVo")
                if codes:
                    res_list = []
                    for c in codes:
                        name = c.findtext("koreBrkd")
                        if not kw or kw in name:
                            res_list.append({"통계부호": c.findtext("statsSgn"), "한글내역": name, "내국세율": c.findtext("itxRt")})
                    st.dataframe(pd.DataFrame(res_list), hide_index=True, use_container_width=True)
                else: st.warning("결과가 없습니다.")
            except Exception as e: st.error(f"연결 오류: {e}")

# --- [Tab 4] 화물통관진행정보 (관세사님 확정 로직 고정) ---
with tabs[3]:
    st.subheader("📦 실시간 화물통관 진행정보 조회")
    CR_API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
    col1, col2, col3 = st.columns([1.5, 3, 1])
    with col1: carg_year = st.selectbox("입항년도", [2026, 2025, 2024, 2023], index=0)
    with col2: bl_no = st.text_input("B/L 번호 입력", placeholder="HBL 또는 MBL 번호", key="bl_final_v3")
    if st.button("실시간 조회", use_container_width=True) and bl_no:
        with st.spinner("조회 중..."):
            url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
            params = {"crkyCn": CR_API_KEY, "blYy": str(carg_year), "hblNo": bl_no.strip().upper()}
            try:
                response = requests.get(url, params=params, timeout=30)
                root = ET.fromstring(response.content)
                info = root.find(".//cargCsclPrgsInfoQryVo")
                if info is not None:
                    status = info.findtext('prgsStts')
                    st.success(f"✅ 현재상태: {status}")
                    m1, m2, m3 = st.columns(3)
                    m1.metric("진행상태", status)
                    m2.metric("품명", info.findtext("prnm")[:12])
                    m3.metric("중량", f"{info.findtext('ttwg')} {info.findtext('wghtUt')}")
                    # 상세 이력
                    history = [{"처리단계": i.findtext("cargTrcnRelaBsopTpcd"), "처리일시": i.findtext("prcsDttm"), "장소": i.findtext("shedNm")} for i in root.findall(".//cargCsclPrgsInfoDtlQryVo")]
                    st.dataframe(pd.DataFrame(history), hide_index=True, use_container_width=True)
                else: st.warning("조회 결과 없음")
            except Exception as e: st.error(e)

# --- [Tab 6] 관리자 (사용자 승인) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.header("⚙️ 사용자 계정 관리")
        conn = sqlite3.connect("users.db")
        users = pd.read_sql("SELECT id, name, is_approved FROM users", conn)
        st.dataframe(users, use_container_width=True)
        target_id = st.text_input("승인할 사용자 ID")
        if st.button("승인 처리"):
            conn.execute("UPDATE users SET is_approved=1 WHERE id=?", (target_id,))
            conn.commit(); st.rerun()
        conn.close()

# --- 하단 푸터 (관세사님 확정 고정) ---
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")