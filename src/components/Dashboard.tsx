import React, { useEffect, useState } from "react";
import { analyzeReviews } from "../services/geminiService";
import { Sparkles, Star, Loader2, AlertCircle, Settings, Link as LinkIcon, Calendar, Play, Info } from "lucide-react";
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

  // 수집 설정 상태
  const [targetUrl, setTargetUrl] = useState<string>("");
  const [startDate, setStartDate] = useState<string>("");
  const [isCollecting, setIsCollecting] = useState<boolean>(false);

  // 컴포넌트가 마운트될 때 리뷰 데이터를 불러옵니다.
  useEffect(() => {
    const fetchReviews = async () => {
      try {
        const response = await fetch("/data/reviews.json");
        // 파일이 없거나 404인 경우 에러 처리 대신 빈 배열로 처리
        if (!response.ok) {
          if (response.status === 404) {
            setReviews([]);
            setError("");
            return;
          }
          throw new Error("리뷰 데이터를 불러오는데 실패했습니다.");
        }
        const data = await response.json();
        setReviews(data || []);
        setError("");
      } catch (err: any) {
        setReviews([]);
        setError("리뷰 데이터를 가져올 수 없습니다. 크롤링 스크립트가 실행되어 /public/data/reviews.json 경로에 데이터가 생성되었는지 확인해주세요.");
        console.error(err);
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
    // 실제 환경에서는 여기서 GitHub Actions Dispatch API나 백엔드 API를 콜합니다.
    setTimeout(() => {
      setIsCollecting(false);
      alert("크롤링 시작 요청이 GitHub Actions로 전송되었습니다. (시뮬레이션)");
    }, 1500);
  };

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-8 font-sans">
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-gray-200">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 tracking-tight">구글 맵 리뷰 분석 대시보드</h1>
          <p className="text-gray-500 mt-2 text-sm">리뷰 데이터를 시각화하고 Gemini AI로 인사이트를 도출해보세요.</p>
        </div>
        <button
          onClick={handleAnalyze}
          disabled={isAnalyzing || reviews.length === 0}
          className="inline-flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white font-medium rounded-xl hover:bg-blue-700 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-sm hover:shadow"
        >
          {isAnalyzing ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <Sparkles className="w-5 h-5 text-blue-100" />
          )}
          <span>{isAnalyzing ? "AI 분석 중..." : "Gemini AI로 분석하기"}</span>
        </button>
      </header>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <p className="text-red-700 text-sm font-medium">{error}</p>
        </div>
      )}

      {/* 수집 설정 섹션 */}
      <section className="bg-white p-6 rounded-2xl border border-gray-200 shadow-sm transition-all hover:shadow-md">
        <div className="flex items-center gap-2 mb-4">
          <Settings className="w-5 h-5 text-gray-700" />
          <h2 className="text-lg font-bold text-gray-900">수집 설정</h2>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-700 flex items-center gap-2">
              <LinkIcon className="w-4 h-4 text-gray-400" />
              구글 맵 URL
            </label>
            <input 
              type="url" 
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              placeholder="https://maps.google.com/..." 
              className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all text-sm"
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-700 flex items-center gap-2">
              <Calendar className="w-4 h-4 text-gray-400" />
              수집 시작 날짜
            </label>
            <input 
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all text-sm text-gray-700"
            />
          </div>
        </div>

        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pt-4 border-t border-gray-100">
          <div className="flex items-start gap-2 text-sm text-gray-500 bg-gray-50/80 p-3 rounded-lg flex-1">
            <Info className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5" />
            <p>여기서 입력한 값은 GitHub로 전달되어 크롤링을 시작합니다. 일정 시간이 지난 후 대시보드 화면을 새로고침하면 최신 데이터가 반영됩니다.</p>
          </div>
          <button 
            onClick={handleStartCollection}
            disabled={isCollecting || !targetUrl || !startDate}
            className="flex-shrink-0 inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-gray-800 text-white font-medium rounded-lg hover:bg-gray-900 transition-all disabled:opacity-50 disabled:cursor-not-allowed w-full sm:w-auto shadow-sm"
          >
            {isCollecting ? <Loader2 className="w-4 h-4 animate-spin outline-none" /> : <Play className="w-4 h-4" />}
            새 데이터 수집 시작
          </button>
        </div>
      </section>

      {/* AI 분석 결과 섹션 */}
      {analysisResult && (
        <section className="bg-gradient-to-br from-indigo-50 to-blue-50/50 p-8 rounded-2xl border border-blue-100 shadow-sm animate-in fade-in slide-in-from-bottom-4 duration-500">
          <h2 className="text-xl font-bold text-gray-900 mb-6 flex items-center gap-2">
            <Sparkles className="w-6 h-6 text-blue-600" />
            AI 리뷰 분석 리포트
          </h2>
          <div className="prose prose-blue prose-sm md:prose-base max-w-none prose-headings:font-semibold prose-li:text-gray-700">
            <ReactMarkdown>{analysisResult}</ReactMarkdown>
          </div>
        </section>
      )}

      {/* 리뷰 목록 섹션 */}
      <section>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold text-gray-900">수집된 최근 리뷰</h2>
          {!isLoadingReviews && (
            <span className="text-sm font-medium text-gray-500 bg-gray-100 px-3 py-1 rounded-full">
              총 {reviews.length}개
            </span>
          )}
        </div>

        {isLoadingReviews ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400 gap-3">
            <Loader2 className="w-8 h-8 animate-spin" />
            <p className="text-sm">데이터를 불러오는 중입니다...</p>
          </div>
        ) : reviews.length === 0 && !error ? (
          <div className="text-center py-20 bg-gray-50 rounded-2xl border border-gray-100 border-dashed">
            <p className="text-gray-500 font-medium">수집된 리뷰가 없습니다.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {reviews.map((review, index) => {
              const isPositive = review.rating >= 4;
              const isNegative = review.rating <= 2;
              
              return (
                <div 
                  key={index} 
                  className="bg-white p-6 rounded-2xl border border-gray-200 shadow-sm hover:shadow-md transition-shadow flex flex-col gap-4"
                >
                  <div className="flex justify-between items-start">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center font-bold text-gray-600 text-sm">
                        {review.author?.charAt(0) || "알"}
                      </div>
                      <div>
                        <p className="text-sm font-bold text-gray-900">{review.author}</p>
                        <p className="text-xs text-gray-500">{review.date}</p>
                      </div>
                    </div>
                    <div className={`flex items-center px-2.5 py-1 rounded-full text-xs font-bold ${
                      isPositive ? "bg-green-100 text-green-700" :
                      isNegative ? "bg-red-100 text-red-700" :
                      "bg-yellow-100 text-yellow-700"
                    }`}>
                      <Star className="w-3.5 h-3.5 mr-1 fill-current" />
                      {review.rating}.0
                    </div>
                  </div>
                  <p className="text-gray-700 text-sm leading-relaxed whitespace-pre-wrap flex-grow">
                    {review.text}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
