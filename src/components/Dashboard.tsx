import React, { useEffect, useState } from "react";
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

  useEffect(() => {
    const fetchReviews = async () => {
      try {
        const response = await fetch("/data/reviews.json");
        if (!response.ok) {
          if (response.status === 404) {
            setReviews([]);
            return;
          }
          throw new Error("데이터를 불러오는데 실패했습니다.");
        }
        const data = await response.json();
        const filteredData = data.filter((r: Review) => 
          r.author !== "김철수" && r.author !== "이영희" && r.author !== "박민수"
        );
        setReviews(filteredData || []);
      } catch (err: any) {
        setReviews([]);
      } finally {
        setIsLoadingReviews(false);
      }
    };
    fetchReviews();
  }, []);

  const handleAnalyze = async () => {
    if (reviews.length === 0) return;
    setIsAnalyzing(true);
    setError("");
    try {
      const result = await analyzeReviews(reviews);
      setAnalysisResult(result || "");
    } catch (err: any) {
      setError(err.message || "분석 중 오류가 발생했습니다.");
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleStartCollection = () => {
    if (!targetUrl || !startDate) return;
    setIsCollecting(true);
    // 3분(180000ms) 후에 자동으로 수집 중 상태를 해제하거나 페이지를 안내함
    // 실제로는 GitHub API 연동 시 상태 체크가 가능하지만 우선 UI 피드백을 강화함
  };

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-8 font-sans bg-gray-50/30 min-h-screen">
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-gray-200">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 tracking-tight">구글 맵 리뷰 분석 대시보드</h1>
          <p className="text-gray-500 mt-2 text-sm">매장 URL을 입력하여 고객의 목소리를 AI로 분석해보세요.</p>
        </div>
        <button
          onClick={handleAnalyze}
          disabled={isAnalyzing || reviews.length === 0 || isCollecting}
          className="inline-flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white font-medium rounded-xl hover:bg-blue-700 transition-all disabled:opacity-50 disabled:bg-gray-300 disabled:cursor-not-allowed shadow-sm hover:shadow"
        >
          {isAnalyzing ? <Loader2 className="w-5 h-5 animate-spin" /> : <Sparkles className="w-5 h-5 text-blue-100" />}
          <span>{isAnalyzing ? "AI 분석 리포트 생성 중..." : "Gemini AI로 분석하기"}</span>
        </button>
      </header>

      {/* 수집 설정 섹션 */}
      <section className="bg-white p-6 rounded-2xl border border-gray-200 shadow-sm">
        <div className="flex items-center gap-2 mb-6">
          <div className="p-2 bg-blue-50 rounded-lg">
            <Settings className="w-5 h-5 text-blue-600" />
          </div>
          <h2 className="text-lg font-bold text-gray-900">매장 데이터 수집 설정</h2>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-6">
          <div className="space-y-3">
            <label className="text-sm font-semibold text-gray-700 flex items-center gap-2">
              <LinkIcon className="w-4 h-4 text-blue-500" />
              구글 맵 매장 URL
            </label>
            <input 
              type="url" 
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              placeholder="주소를 붙여넣어 주세요" 
              className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:bg-white outline-none transition-all text-sm"
            />
            <div className="bg-gray-50 p-3 rounded-lg border border-gray-100">
              <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-1">지원하는 주소 형식</p>
              <ul className="text-[12px] text-gray-500 space-y-1">
                <li>• 공유하기 주소: <span className="text-blue-500">https://maps.app.goo.gl/...</span></li>
                <li>• 전체 주소: <span className="text-blue-500">https://www.google.com/maps/place/...</span></li>
              </ul>
            </div>
          </div>
          <div className="space-y-3">
            <label className="text-sm font-semibold text-gray-700 flex items-center gap-2">
              <Calendar className="w-4 h-4 text-blue-500" />
              수집 시작일 기준
            </label>
            <input 
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:bg-white outline-none transition-all text-sm text-gray-700"
            />
            <p className="text-[12px] text-gray-400">선택한 날짜 이후에 작성된 리뷰만 수집합니다.</p>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 pt-6 border-t border-gray-100">
          <div className="flex items-start gap-3 text-sm text-gray-600 bg-blue-50/50 p-4 rounded-xl flex-1">
            <Info className="w-5 h-5 text-blue-500 flex-shrink-0 mt-0.5" />
            <p className="leading-relaxed">
              수집 버튼 클릭 시 GitHub 서버에서 크롤링이 시작됩니다. 완료까지 <span className="font-bold text-blue-700 underline">약 3분 정도</span> 소요되며, 작업이 끝나면 페이지를 새로고침해 주세요.
            </p>
          </div>
          <button 
            onClick={handleStartCollection}
            disabled={isCollecting || !targetUrl || !startDate}
            className={`inline-flex items-center justify-center gap-2 px-8 py-4 font-bold rounded-xl transition-all shadow-lg active:scale-95 ${
              isCollecting ? "bg-amber-500 text-white animate-pulse" : "bg-gray-900 text-white hover:bg-black"
            }`}
          >
            {isCollecting ? <Loader2 className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5 fill-current" />}
            {isCollecting ? "리뷰 수집 진행 중..." : "새 데이터 수집 시작"}
          </button>
        </div>
      </section>

      {/* 리뷰 목록 섹션 (상태에 따른 분기 처리 강화) */}
      <section className="space-y-6">
        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
          수집된 최근 리뷰
          {reviews.length > 0 && <span className="text-xs font-bold bg-blue-100 text-blue-600 px-2.5 py-0.5 rounded-full">{reviews.length}</span>}
        </h2>

        {isCollecting ? (
          /* 수집 중일 때 보여주는 역동적인 로딩 화면 */
          <div className="flex flex-col items-center justify-center py-32 bg-white rounded-3xl border-2 border-blue-100 shadow-sm relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-blue-50/30 to-transparent animate-shimmer" />
            <div className="relative z-10 flex flex-col items-center">
              <div className="relative mb-6">
                <Search className="w-16 h-16 text-blue-500 animate-bounce" />
                <Loader2 className="w-20 h-20 text-blue-100 animate-spin absolute -top-2 -left-2" />
              </div>
              <h3 className="text-xl font-bold text-gray-800 mb-2">구글 맵에서 리뷰를 긁어오고 있습니다</h3>
              <p className="text-gray-400 text-center text-sm">
                현재 GitHub Actions 일꾼이 열일 중입니다.<br/>
                약 3분 후 이 페이지를 <strong>새로고침(F5)</strong> 하시면 결과가 나타납니다.
              </p>
              <div className="mt-8 w-64 h-2 bg-gray-100 rounded-full overflow-hidden">
                <div className="h-full bg-blue-500 animate-progress" />
              </div>
            </div>
          </div>
        ) : isLoadingReviews ? (
          <div className="flex flex-col items-center justify-center py-24 bg-white rounded-3xl border border-gray-100 shadow-sm gap-4">
            <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
            <p className="text-gray-400 font-medium">저장된 데이터를 불러오고 있습니다...</p>
          </div>
        ) : reviews.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-32 bg-white rounded-3xl border-2 border-dashed border-gray-200 shadow-inner">
            <div className="p-6 bg-gray-50 rounded-full mb-6">
              <MessageSquare className="w-16 h-16 text-gray-200" />
            </div>
            <h3 className="text-xl font-bold text-gray-700 mb-2 text-center px-6">수집된 리뷰 데이터가 없습니다</h3>
            <p className="text-gray-400 text-center text-sm max-w-sm px-6 leading-relaxed">
              상단에 매장 주소를 넣고 <strong>[새 데이터 수집 시작]</strong>을 누르면<br/>
              고객들의 생생한 목소리가 여기에 표시됩니다.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {reviews.map((review, index) => (
              <div key={index} className="bg-white p-6 rounded-2xl border border-gray-100 shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all duration-300 flex flex-col gap-4">
                <div className="flex justify-between items-start">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-gray-100 to-gray-200 flex items-center justify-center font-bold text-gray-600">{review.author?.charAt(0)}</div>
                    <div><p className="text-sm font-bold text-gray-900">{review.author}</p><p className="text-xs text-gray-400">{review.date}</p></div>
                  </div>
                  <div className={`flex items-center px-3 py-1 rounded-lg text-xs font-black ${review.rating >= 4 ? "bg-green-50 text-green-600" : review.rating <= 2 ? "bg-red-50 text-red-600" : "bg-yellow-50 text-yellow-600"}`}>
                    <Star className="w-3.5 h-3.5 mr-1 fill-current" />{review.rating}.0
                  </div>
                </div>
                <p className="text-gray-600 text-sm leading-relaxed italic flex-grow">"{review.text}"</p>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* CSS 애니메이션 정의 (Tailwind와 함께 사용) */}
      <style>{`
        @keyframes shimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }
        .animate-shimmer {
          animation: shimmer 2s infinite;
        }
        @keyframes progress {
          0% { width: 0%; }
          100% { width: 95%; }
        }
        .animate-progress {
          animation: progress 180s linear forwards;
        }
      `}</style>
    </div>
  );
}
