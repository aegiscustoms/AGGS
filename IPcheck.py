import streamlit as st
import dns.resolver

st.title("상세 DNS A 레코드 조회")

domain = st.text_input("도메인 입력", "naver.com")

if st.button("A 레코드 확인"):
    try:
        # A 레코드 쿼리
        result = dns.resolver.resolve(domain, 'A')
        ip_list = [ip.to_text() for ip in result]
        
        st.write(f"{domain}의 IP 주소들:")
        for ip in ip_list:
            st.code(ip) # 코드 블록 형태로 깔끔하게 출력
    except Exception as e:
        st.error(f"조회 실패: {e}")