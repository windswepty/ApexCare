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
        # 1차 시도: 최신 Flash 모델
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash-latest",
            system_instruction=SYSTEM_PROMPT
        )
        response = model.generate_content(content)
        return {"success": True, "answer": response.text}
            
    except Exception as e1:
        # 2차 시도: 가장 안정적인 범용 모델 gemini-pro
        try:
            fallback_model = genai.GenerativeModel(
                model_name="gemini-pro",
                # gemini-pro는 system_instruction 파라미터를 미지원하는 경우가 있으므로 안전하게 프롬프트와 결합
            )
            combined_content = f"{SYSTEM_PROMPT}\n\n{content}"
            response = fallback_model.generate_content(combined_content)
            return {"success": True, "answer": response.text}
            
        except Exception as e2:
            # 3차 시도 (마지막 수단): 극단적 호환 모드 (PaLM Legacy 또는 gemini-1.0-pro)
            try:
                # gemini-1.0-pro-latest 또는 text-bison 
                final_model = genai.GenerativeModel("gemini-1.0-pro-latest")
                combined_content = f"[{SYSTEM_PROMPT}]\n위 역할을 수행하라.\n\n{content}"
                response = final_model.generate_content(combined_content)
                return {"success": True, "answer": f"**(호환 모드로 작성됨)**\n\n{response.text}"}
                
            except Exception as e3:
                return {
                    "success": False, 
                    "error": f"API 호출 3중 방어 실패 (모든 모델 호환 불가):\n1차(flash): {str(e1)}\n2차(pro): {str(e2)}\n3차(legacy): {str(e3)}\n\nAPI 키의 권한이나 라이브러리 버전을 확인해 주세요."
                }
