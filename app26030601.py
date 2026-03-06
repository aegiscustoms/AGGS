import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import io
import requests
import xml.etree.ElementTree as ET

# --- 전역 설정 및 폰트 사양 ---
TITLE_FONT_SIZE = "15px"
CONTENT_FONT_SIZE = "12px"
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/xml"
}

# --- 1. 초기 DB 설정 (사용자 관리용) ---
def init_db():
    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    admin_id = "aegis01210"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, name, is_approved, is_admin) VALUES (?, ?, ?, 1, 1)", 
                      (admin_id, admin_pw, "관리자"))
    conn_auth.commit()
    conn_auth.close()

init_db()

# Gemini API 설정
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 및 세션 관리 ---
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
        else: st.error("정보 불일치 또는 승인 대기")
    st.stop()

# --- 3. 메인 화면 상단 ---
st.sidebar.write(f"✅ {st.session_state.user_name} 접속 중")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관진행정보", "🧮 세액계산기"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 (관세사님 확정 고정 로직) ---
with tabs[0]:
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("품명/물품정보(용도/기능/성분/재질) 입력", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"], key="hs_i")
    if u_img: st.image(Image.open(u_img), caption="📸 분석 대상 이미지", width=300)
    if st.button("HS분석 실행", use_container_width=True):
        if u_img or u_input:
            with st.spinner("분석 중..."):
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
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📘 실시간 HS부호 정보 (Uni-Pass)</div>", unsafe_allow_html=True)
    RATE_KEY = st.secrets.get("RATE_API_KEY", "").strip()
    target_hs = st.text_input("HS코드 10자리 입력", placeholder="예: 0302440000", key="hs_rate_api")
    if st.button("실시간 HS 정보 조회", use_container_width=True):
        if target_hs:
            with st.spinner("가이드 명세에 따른 데이터 조회 중..."):
                # 가이드 URL 규격 반영
                url = "https://unipass.customs.go.kr:38010/ext/rest/hsSgnQry/searchHsSgn"
                params = {"crkyCn": RATE_KEY, "hsSgn": target_hs.strip(), "koenTp": "1"}
                try:
                    res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
                    root = ET.fromstring(res.content)
                    # 가이드 응답 태그: korePrnm, txrt 등
                    item = root.find(".//hsSgnQryVo")
                    if item is not None:
                        st.info(f"✅ 한글품명: {item.findtext('korePrnm')}")
                        st.write(f"영문품명: {item.findtext('englPrnm')}")
                        st.success(f"적용세율: {item.findtext('txrt') or '정보없음'}")
                        st.write(f"수량단위: {item.findtext('qtyUt')} / 중량단위: {item.findtext('wghtUt')}")
                    else:
                        st.warning("정보를 찾을 수 없습니다. 인증키의 'API018' 승인 여부와 HS코드를 확인하세요.")
                except Exception as e: st.error(f"API 연결 실패: {e}")

# --- [Tab 3] 통계부호 (가이드 API019 정밀 반영) ---
with tabs[2]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📊 실시간 통계부호 검색 (Uni-Pass)</div>", unsafe_allow_html=True)
    STAT_KEY = st.secrets.get("STAT_API_KEY", "").strip()
    # 가이드 기반 분류코드 매핑
    clft_dict = {"관세감면/분납": "A01", "내국세율": "A04", "용도부호": "A05", "보세구역": "A08"}
    col1, col2 = st.columns([1, 2])
    with col1: sel_clft = st.selectbox("분류 선택", list(clft_dict.keys()))
    with col2: kw = st.text_input("부호명 키워드 검색", placeholder="예: 정밀전자")
    
    if st.button("부호 실시간 검색", use_container_width=True):
        with st.spinner("가이드 명세에 따른 코드 검색 중..."):
            # 가이드 URL 및 필수 파라미터(statsSgnclftCd) 반영
            url = "https://unipass.customs.go.kr:38010/ext/rest/statsSgnQry/retrieveStatsSgnBrkd"
            params = {"crkyCn": STAT_KEY, "statsSgnclftCd": clft_dict[sel_clft]}
            try:
                res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
                root = ET.fromstring(res.content)
                codes = root.findall(".//statsSgnQryVo")
                if codes:
                    res_list = []
                    for c in codes:
                        name = c.findtext("koreBrkd")
                        if not kw or kw in name:
                            res_list.append({"통계부호": c.findtext("statsSgn"), "한글내역": name, "비고(세율 등)": c.findtext("itxRt")})
                    st.dataframe(pd.DataFrame(res_list), hide_index=True, use_container_width=True)
                else:
                    st.warning("결과가 없습니다. 인증키의 'API019' 승인 여부를 확인하세요.")
            except Exception as e: st.error(f"API 연결 실패: {e}")

# --- [Tab 4] 화물통관진행정보 (관세사님 요청 복구 버전) ---
with tabs[3]:
    st.subheader("📦 실시간 화물통관 진행정보 조회")
    CR_API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
    if not CR_API_KEY:
        st.error("⚠️ Streamlit Secrets에 'UNIPASS_API_KEY'가 설정되지 않았습니다."); st.stop()

    col1, col2, col3 = st.columns([1.5, 3, 1])
    with col1: carg_year = st.selectbox("입항년도", [2026, 2025, 2024, 2023], index=0)
    with col2: bl_no = st.text_input("B/L 번호 입력", placeholder="HBL 또는 MBL 번호", key="bl_final_v3")
    with col3: st.write(""); search_btn = st.button("실시간 조회", use_container_width=True)

    if search_btn:
        if not bl_no:
            st.warning("B/L 번호를 입력해 주세요.")
        else:
            with st.spinner("관세청 유니패스에서 데이터를 가져오는 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
                params = {"crkyCn": CR_API_KEY, "blYy": str(carg_year), "hblNo": bl_no.strip().upper()}
                try:
                    response = requests.get(url, params=params, timeout=30)
                    if response.status_code == 200:
                        root = ET.fromstring(response.content)
                        t_cnt = root.findtext(".//tCnt")
                        if t_cnt and int(t_cnt) > 0:
                            info = root.find(".//cargCsclPrgsInfoQryVo")
                            current_status = info.findtext('prgsStts')
                            st.success(f"✅ 화물 확인됨: {current_status}")
                            m1, m2, m3 = st.columns(3)
                            m1.metric("진행상태", current_status)
                            m2.metric("품명", info.findtext("prnm")[:12] if info.findtext("prnm") else "-")
                            m3.metric("중량", f"{info.findtext('ttwg')} {info.findtext('wghtUt')}")
                            st.markdown("---")
                            st.markdown(f"""
                            <div class='custom-text'>
                            <b>• 선박/항공기명:</b> {info.findtext('shipNm')}<br>
                            <b>• 입항일자:</b> {info.findtext('etprDt')}<br>
                            <b>• 현재위치:</b> {info.findtext('shcoFlco')}<br>
                            <b>• MBL 번호:</b> {info.findtext('mblNo')}
                            </div>
                            """, unsafe_allow_html=True)
                            st.markdown("#### 🕒 처리 단계별 상세 이력")
                            history = []
                            for item in root.findall(".//cargCsclPrgsInfoDtlQryVo"):
                                history.append({
                                    "처리단계": item.findtext("cargTrcnRelaBsopTpcd"),
                                    "처리일시": item.findtext("prcsDttm"),
                                    "장치장/내용": item.findtext("shedNm") if item.findtext("shedNm") else item.findtext("rlbrCn"),
                                    "포장개수": f"{item.findtext('pckGcnt')} {item.findtext('pckUt')}"
                                })
                            st.dataframe(pd.DataFrame(history).style.set_properties(**{'text-align': 'center', 'font-size': '12px'}), hide_index=True, use_container_width=True)
                        else: st.warning("조회된 정보가 없습니다.")
                    else: st.error(f"❌ 접속 오류 (Status: {response.status_code})")
                except Exception as e: st.error(f"⚠️ 연결 실패: {str(e)}")

# --- [Tab 6] 관리자 페이지 (아이디/비밀번호 관리 전용) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.header("⚙️ 사용자 계정 관리")
        conn = sqlite3.connect("users.db")
        df_users = pd.read_sql("SELECT id, name, is_approved FROM users", conn)
        st.dataframe(df_users, hide_index=True, use_container_width=True)
        
        target_id = st.text_input("처리할 사용자 ID 입력")
        c1, c2 = st.columns(2)
        if c1.button("가입 승인"):
            conn.execute("UPDATE users SET is_approved=1 WHERE id=?", (target_id,))
            conn.commit(); st.rerun()
        if c2.button("계정 삭제"):
            conn.execute("DELETE FROM users WHERE id=?", (target_id,))
            conn.commit(); st.rerun()
        conn.close()

# --- 하단 푸터 (관세사님 확정 고정) ---
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")