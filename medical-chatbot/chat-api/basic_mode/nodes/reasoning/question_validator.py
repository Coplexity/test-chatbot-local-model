from core import config
from core.llm_client import get_llm
from basic_mode.core.schemas import RouterState, ValidationResult
from basic_mode.core.prompts import QUESTION_VALIDATION_PROMPT


class QuestionValidatorNode:
    """Node xác nhận & phân loại câu hỏi thành greeting/medical/off_topic"""

    def __init__(self):
        print("⏳ [Validator] Initializing Question Validator...")
        self.llm = get_llm(temperature=0)

    def process(self, state: RouterState):
        query = state["query"]
        structured_llm = self.llm.with_structured_output(ValidationResult, method=config.LLM_STRUCTURED_OUTPUT_METHOD)

        prompt = QUESTION_VALIDATION_PROMPT.format(query=query)

        try:
            result = structured_llm.invoke(prompt)
            category = result.category
            is_medical = (category == "medical")

            print(f"✅ [Validator] Query classification: category={category}, is_medical={is_medical}")
            return {
                "validation_category": category,
                "is_medical_related": is_medical,
            }
        except Exception as e:
            print(f"❌ [Validator Error] {e}")
            # Fallback: giả sử câu hỏi liên quan y tế
            return {
                "validation_category": "medical",
                "is_medical_related": True,
            }
