import google.generativeai as genai
from backend.config_manager import get_ai_api_key

SYSTEM_PROMPT = """당신은 'APEX CARE'라는 윈도우 PC 최적화 프로그램에 내장된 'AI 문제 해결사(AI Problem Solver)'이자, 세계 최고 수준의 Windows OS 및 PC 하드웨어 최적화 전문가입니다.
사용자가 소프트웨어 에러 로그나 최적화 실패 내역, PC 상태 정보를 전달하면, 그 원인을 정확히 분석하고 사용자가 이해하기 쉬운 친절한 한국어로 단계별 해결책을 제시해야 합니다.

[중요 지침]
1. Read-Only 원칙: 당신은 시스템을 직접 제어할 수 없습니다. 오직 조언과 가이드만 제공해야 합니다.
2. 마크다운 활용: 중요한 키워드나 코드, 경로 등은 마크다운 문법(`코드`나 **강조**)을 사용해 가독성 있게 작성하세요.
3. 친절하고 직관적인 어조: 너무 기계적이지 않게, 실제 전문가가 곁에서 도와주는 것처럼 부드러운 어조를 사용하세요.
4. 원인과 해결책 명시: '에러 원인'과 '해결 방법'을 명확히 구분하여 답변하세요.
"""

def analyze_error_with_ai(error_log, system_state, user_message=""):
    api_key = get_ai_api_key()
    if not api_key:
        return {"success": False, "error": "API 키가 설정되지 않았습니다. 설정에서 Gemini API 키를 입력해주세요."}

    genai.configure(api_key=api_key)
    
    # Prompt 구성
    content = f"**[시스템 상태 정보]**\n{system_state}\n\n**[발생한 에러/로그]**\n{error_log}\n\n"
    if user_message:
        content += f"**[사용자 메시지]**\n{user_message}"
        
    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash-latest",
            system_instruction=SYSTEM_PROMPT
        )
        response = model.generate_content(content)
        return {"success": True, "answer": response.text}
            
    except Exception as e:
        # Fallback to gemini-1.5-pro or older stable if 404 or other errors occur
        try:
            fallback_model = genai.GenerativeModel(
                model_name="gemini-1.5-pro",
                system_instruction=SYSTEM_PROMPT
            )
            response = fallback_model.generate_content(content)
            return {"success": True, "answer": response.text}
        except Exception as fallback_e:
            return {"success": False, "error": f"API 호출 또는 네트워크 오류 (Fallback 실패): 기본 에러({str(e)}), Fallback 에러({str(fallback_e)})"}
