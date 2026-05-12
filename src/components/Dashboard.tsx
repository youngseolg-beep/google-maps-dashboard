import React, { useEffect, useState, useRef } from "react";
import { analyzeReviews } from "../services/geminiService";
import { Sparkles, Star, Loader2, AlertCircle, Settings, Link as LinkIcon, Calendar, Play, Info, MessageSquare, Search } from "lucide-react";
import ReactMarkdown from 'react-markdown';

interface Review {
  author: string;
  rating: number;
  text: string;
  date: string;
}

export default function Dashboard() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [analysisResult, setAnalysisResult] = useState<string>("");
  const [isAnalyzing, setIsAnalyzing] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [isLoadingReviews, setIsLoadingReviews] = useState<boolean>(true);

  const [targetUrl, setTargetUrl] = useState<string>("");
  const [startDate, setStartDate] = useState<string>("");
  const [isCollecting, setIsCollecting] = useState<boolean>(false);
  const [expectedMinutes, setExpectedMinutes] = useState<number>(0);
  const pollingInterval = useRef<NodeJS.Timeout | null>(null);

  // 오늘 날짜 구하기 (YYYY-MM-DD 형식) - 미래 날짜 선택 방지용
  const today = new Date().toISOString().split('T')[0];

  const fetchReviews = async (showLoading = true) => {
    if (showLoading) setIsLoadingReviews(true);
    try {
      const response = await fetch(`/data/reviews.json?t=${new Date().getTime()}`);
      if (!response.ok) return;
      
      const data = await response.json();
      const validData = (data || []).filter((r: Review) => 
        r.author !== "김철수" && r.author !== "이영희" && r.author !== "박민수"
      );

      if (validData.length > 0) {
        setReviews(validData);
        if (isCollecting) {
          setIsCollecting(false);
          if (pollingInterval.current) clearInterval(pollingInterval.current);
          alert("✅ 수집 완료! 최신 리뷰 데이터를 불러왔습니다.");
        }
      }
    } catch (err) {
      console.error(err);
    } finally {
      if (showLoading) setIsLoadingReviews(false);
    }
  };

  useEffect(() => {
    fetchReviews();
    return () => { if (pollingInterval.current) clearInterval(pollingInterval.current); };
  }, []);

  const handleStartCollection = () => {
    if (!targetUrl || !startDate) return;

    const diffDays = Math.ceil(Math.abs(new Date().getTime() - new Date(startDate).getTime()) / (1000 * 60 * 60 * 24));
    
    let duration = 120; // 기본 2분
    let mins = 2;

    if (diffDays <= 14) { duration = 60; mins = 1; } // 2주 이내는 1분으로 단축
    else if (diffDays <= 60) { duration = 180; mins = 3; }
    else { duration = 420; mins = 7; }

    setExpectedMinutes(mins);
    document.documentElement.style.setProperty('--collect-duration', `${duration}s`);
    setIsCollecting(true);
    setReviews([]); 

    pollingInterval.current = setInterval(() => {
      fetchReviews(false);
    }, 15000);
  };

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-8 font-sans bg-gray-50/30 min-h-screen">
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-gray-200">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 tracking-tight">구글 맵 리뷰 분석 대시보드</h1>
          <p className="text-gray-500 mt-2 text-sm">매장 주소를 입력하여 고객 리뷰를 초고속으로 수집하고 AI로 분석하세요.</p>
        </div>
        <button
          onClick={async () => {
            setIsAnalyzing(true);
            try {
              const result = await analyzeReviews(reviews);
              setAnalysisResult(result || "");
            } catch (err: any) {
              setError("분석 중 오류가 발생했습니다.");
            } finally {
              setIsAnalyzing(false);
            }
          }}
          disabled={isAnalyzing || reviews.length === 0 || isCollecting}
          className="inline-flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white font-bold rounded-xl hover:bg-blue-700 transition-all disabled:opacity-50 disabled:bg-gray-300"
        >
          {isAnalyzing ? <Loader2 className="w-5 h-5 animate-spin" /> : <Sparkles className="w-5 h-5" />}
          <span>{isAnalyzing ? "분석 중..." : "AI 리포트 생성"}</span>
        </button>
      </header>

      {/* 설정 섹션 */}
      <section className="bg-white p-6 rounded-2xl border border-gray-200 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-6">
          <div className="space-y-3">
            <label className="text-sm font-bold text-gray-700">구글 맵 매장 URL</label>
            <input 
              type="url" 
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              placeholder="공유 주소 또는 상세 주소 붙여넣기" 
              className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none text-sm"
            />
            <div className="p-3 bg-blue-50 rounded-lg text-[11px] text-blue-600 leading-relaxed">
              <strong>💡 지원 주소:</strong> maps.app.goo.gl/... 또는 google.com/maps/place/...
            </div>
          </div>
          <div className="space-y-3">
            <label className="text-sm font-bold text-gray-700">수집 시작일 (오늘 이후 선택 불가)</label>
            <input 
              type="date"
              value={startDate}
              max={today}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none text-sm text-gray-700"
            />
            <div className="p-3 bg-amber-50 rounded-lg text-[11px] text-amber-700">
              <strong>⏳ 예상 소요:</strong> {startDate ? (Math.ceil(Math.abs(new Date().getTime() - new Date(startDate).getTime()) / (1000 * 60 * 60 * 24)) <= 14 ? "약 1분 이내" : "약 3~5분") : "날짜를 선택하세요"}
            </div>
          </div>
        </div>

        <button 
          onClick={handleStartCollection}
          disabled={isCollecting || !targetUrl || !startDate}
          className={`w-full py-4 font-black rounded-xl transition-all shadow-lg ${
            isCollecting ? "bg-amber-500 text-white animate-pulse" : "bg-gray-900 text-white hover:bg-black"
          }`}
        >
          {isCollecting ? "데이터 수집 중... (이 창을 유지해 주세요)" : "새 데이터 수집 시작"}
        </button>
      </section>

      {/* 분석 결과 */}
      {analysisResult && (
        <section className="bg-white p-8 rounded-3xl border-2 border-blue-100 shadow-xl">
          <div className="prose prose-blue max-w-none">
            <ReactMarkdown>{analysisResult}</ReactMarkdown>
          </div>
        </section>
      )}

      {/* 리뷰 목록 */}
      <section>
        {isCollecting ? (
          <div className="flex flex-col items-center justify-center py-32 bg-white rounded-3xl border-2 border-blue-100 shadow-sm overflow-hidden">
            <div className="relative mb-8">
              <Search className="w-16 h-16 text-blue-500 animate-bounce" />
              <Loader2 className="w-24 h-24 text-blue-50/50 animate-spin absolute -top-4 -left-4" />
            </div>
            <h3 className="text-2xl font-black text-gray-800 mb-2">리뷰를 수집하고 있습니다</h3>
            <p className="text-gray-400 text-sm mb-8 text-center">예상 대기 시간: 약 {expectedMinutes}분 (완료 시 자동 업데이트)</p>
            <div className="w-80 h-3 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full bg-blue-500" style={{ animation: `progress var(--collect-duration) linear forwards` }} />
            </div>
          </div>
        ) : reviews.length === 0 ? (
          <div className="text-center py-32 bg-white rounded-3xl border-2 border-dashed border-gray-200">
            <MessageSquare className="w-16 h-16 text-gray-200 mx-auto mb-6" />
            <p className="text-gray-400">수집된 리뷰가 없습니다. 상단에서 설정을 완료해 주세요.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {reviews.map((r, i) => (
              <div key={i} className="bg-white p-6 rounded-2xl border border-gray-100 shadow-sm hover:shadow-lg transition-all">
                <div className="flex justify-between mb-4">
                  <span className="font-bold text-sm text-gray-900">{r.author}</span>
                  <div className="flex items-center text-xs font-bold text-yellow-600 bg-yellow-50 px-2 py-1 rounded-lg">
                    <Star className="w-3 h-3 mr-1 fill-current" /> {r.rating}.0
                  </div>
                </div>
                <p className="text-gray-600 text-xs italic leading-relaxed">"{r.text}"</p>
                <p className="text-[10px] text-gray-400 mt-4">{r.date}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      <style>{`
        @keyframes progress { 0% { width: 0%; } 100% { width: 98%; } }
        :root { --collect-duration: 120s; }
      `}</style>
    </div>
  );
}
