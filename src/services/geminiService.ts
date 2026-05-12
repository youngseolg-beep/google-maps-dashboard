import { GoogleGenAI } from "@google/genai";

// 수정 후 코드
const apiKey = import.meta.env.VITE_GEMINI_API_KEY || "";

// Initialize the Google GenAI SDK
const ai = new GoogleGenAI({ apiKey: apiKey });

export async function analyzeReviews(reviewsList: Array<any>): Promise<string> {
  if (!reviewsList || reviewsList.length === 0) {
    throw new Error("분석할 리뷰 데이터가 없습니다.");
  }

  const reviewsText = reviewsList
    .map((r, i) => `[리뷰 ${i + 1}] 작성일: ${r.date} | 별점: ${r.rating}점 | 본문: ${r.text}`)
    .join("\n");

  const positiveCount = reviewsList.filter(r => r.rating >= 4).length;
  const negativeCount = reviewsList.filter(r => r.rating <= 2).length;

  const prompt = `
당신은 바쁜 사장님을 위한 리뷰 요약 AI입니다.
아래 리뷰 데이터를 바탕으로 다음 양식에 맞춰 아주 짧고 명확하게 요약해주세요.

[분석할 리뷰 데이터]
${reviewsText}

[지시 사항]
- 아래 형식을 반드시 지켜주세요. 대괄호([]) 부분을 실제 분석 내용으로 채워주세요.

🔴 부정 리뷰 (${negativeCount}건): [한 줄 요약]
🟢 긍정 리뷰 (${positiveCount}건): [한 줄 요약]
🌐 외국어 리뷰 번역: [외국어 리뷰가 있다면 국문 번역 요약, 없으면 생략]
🚀 핵심 액션 플랜: [가장 시급한 것 딱 하나만]
`;

  try {
    const response = await ai.models.generateContent({
      model: "gemini-3-flash-preview", // 빠른 분석 속도를 위해 Flash 모델 사용
      contents: prompt,
      config: {
        temperature: 0.7
      }
    });
    
    return response.text;
  } catch (error: any) {
    console.error("Gemini API Error:", error);
    throw new Error(`리뷰 분석 중 오류가 발생했습니다: ${error.message || error}`);
  }
}
