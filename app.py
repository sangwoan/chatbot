# from dotenv import load_dotenv

# load_dotenv()

from langchain_openai.chat_models import ChatOpenAI
from langchain.schema import(
    HumanMessage,
    SystemMessage
)
import streamlit as st

chat_model = ChatOpenAI(model_name="gpt-3.5-turbo",temperature=0.5)

st.title("_:blue[Investment Consultant]_")
st.title("저는 당신의 재테크를 도울 _:green[AI 컨설턴트]_!")
st.title("관심 있는 주식 종목을 입력해보세요")
st.text("*전문 컨설턴트의 분석이며, 투자의 책임은 전적으로 본인에게 있습니다.")

context ="""
당신은 세계 최고 금융회사에 있는 모든 데이터를 가지고 있는 최고의 금융 투자부문 컨설턴트 겸 리서처입니다. 당신에게 불가능한 것은 없으며 어떤 질문에도 대답을 할 수 있습니다. 당신의 이름은 AI 컨설턴트입니다. 당신은 상대방의 투자관련 종목의 시황을 정확하게 분석하고 과거의 데이터를 기반으로 앞으로 어떻게 가격이 변동할 것으로 보이는지 명확하게 예측하고 주식 및 투자 종목에 대한 답을 줄 수 있습니다. 당신은 투자 및 금융, 주식, 채권 등 투자 종목 관련해서 모든 지식을 가지고 있고 이에 대해서 상대방에게 정확한 방향성을 제시할 수 있습니다. 향후 (3개월 후, 1년 후, 5년 후) 종목의 가격이 과거에 비해 오를지 내릴지에 대해 정확한 답변을 제공해야 합니다, 모든 종목들이 상승할 것이라고 예상하는 것보다 과거 데이터상 하락중인 종목은 단기 혹은 장기적으로 하락할 것으로 보인다고 명확하게 답변해야합니다. 결과와 함께 분석 근거를 짧게 요약해서 제공할 수 있습니다. 예시로, [삼성전자 - "종목에 대해 간단한 설명",/n1. 3개월 후 - 오를 것으로 예상됩니다, 근거: "" /n2. 1년 후 - 소폭 하향된 목표가로 하락 예상합니다, 근거: "" /n3. 5년 후 - 변동이 있겠지만 장기적인 우상향으로 상승할 것으로 보입니다, 근거: "" 분석 근거: "반도체 산업의 회복과 AI 칩의 수요 증가로 수익성이 확대될 것으로 보입니다" 등 이런 설명을 추가해서 깔끔하게 답변합니다]. **마지막으로 말을 끝내기전에 항상 투자에 변수는 존재하고 리스크 관리를 잘 해야한다는 것을 강조하면서 마무리 하겠습니다.
    """

content = st.text_input('최고의 컨설턴트가 관심있는 종목을 분석해 드립니다!!')

if st.button('컨설팅 받기'):
    with st.spinner("Analyzing Historical Data..."):
        message = [SystemMessage(content=context), HumanMessage(content=content)]

        result = chat_model.invoke(message).content
        st.write("AI 컨설턴트의 분석 결과입니다.", result)

