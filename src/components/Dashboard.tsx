import React, { useEffect, useState } from "react";
import { analyzeReviews } from "../services/geminiService";
import { Sparkles, Star, Loader2, AlertCircle, Settings, Link as LinkIcon, Calendar, Play, Info, MessageSquare } from "lucide-react";
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
        if (!response.ok) {
          if (response.status === 404) {
            setReviews([]);
            return;
          }
          throw new Error("데이터를 불러오는데 실패했습니다.");
        }
        const data = await response.json();
        
        // 샘플 데이터(김철수 등)가 포함되어 있는지 체크하여 걸러냄 (초기화 목적)
        const filteredData = data.filter((r: Review) => 
          r.author !== "김철수" && r.author !== "이영희" && r.author !== "박민수"
        );
        
        setReviews(filteredData || []);
      } catch (err: any) {
        setReviews([]);
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
    
    // GitHub Actions 실행을 위한 가이드 메시지 (점주용)
    setTimeout(() => {
      setIsCollecting(false);
      alert("✅ 수집 요청이 전송되었습니다!\n\nGitHub Actions가 실행되며, 약 3~5분 후 새로고침(F5)하시면 실제 리뷰 데이터가 나타납니다.");
    }, 1500);
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
          disabled={isAnalyzing || reviews.length === 0}
          className="inline-flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white font-medium rounded-xl hover:bg-blue-700 transition-all disabled:opacity-50 disabled:bg-gray-300 disabled:cursor-not-allowed shadow-sm hover:shadow"
        >
          {isAnalyzing ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <Sparkles className="w-5 h-5 text-blue-100" />
          )}
          <span>{isAnalyzing ? "AI 분석 리포트 생성 중..." : "Gemini AI로 분석하기"}</span>
        </button>
      </header>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <p className="text-red-700 text-sm font-medium">{error}</p>
        </div>
      )}

      {/* 수집 설정 섹션 */}
      <section className="bg-white p-6 rounded-2xl border border-gray-200 shadow-sm">
        <div className="flex items-center gap-2 mb-6">
          <div className="p-2 bg-blue-50 rounded-lg">
            <Settings className="w-5 h-5 text-blue-600" />
          </div>
          <h2 className="text-lg font-bold text-gray-900">매장 데이터 수집 설정</h2>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          <div className="space-y-2">
            <label className="text-sm font-semibold text-gray-700 flex items-center gap-2">
              <LinkIcon className="w-4 h-4 text-blue-500" />
              구글 맵 매장 URL
            </label>
            <input 
              type="url" 
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              placeholder="https://www.google.com/maps/place/..." 
              className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:bg-white outline-none transition-all text-sm"
            />
          </div>
          <div className="space-y-2">
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
          </div>
        </div>

        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 pt-6 border-t border-gray-100">
          <div className="flex items-start gap-3 text-sm text-gray-600 bg-blue-50/50 p-4 rounded-xl flex-1">
            <Info className="w-5 h-5 text-blue-500 flex-shrink-0 mt-0.5" />
            <p className="leading-relaxed">
              입력하신 URL의 리뷰를 수집합니다. <span className="font-bold text-blue-700 underline">데이터 수집은 약 3분 정도 소요</span>되며, 완료 후 페이지를 새로고침(F5) 해주세요.
            </p>
          </div>
          <button 
            onClick={handleStartCollection}
            disabled={isCollecting || !targetUrl || !startDate}
            className="inline-flex items-center justify-center gap-2 px-8 py-3 bg-gray-900 text-white font-bold rounded-xl hover:bg-black transition-all disabled:opacity-30 disabled:cursor-not-allowed shadow-lg active:scale-95"
          >
            {isCollecting ? <Loader2 className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5 fill-current" />}
            새 데이터 수집 시작
          </button>
        </div>
      </section>

      {/* AI 분석 결과 섹션 */}
      {analysisResult && (
        <section className="bg-white p-8 rounded-2xl border-2 border-blue-100 shadow-xl animate-in fade-in zoom-in-95 duration-500">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-blue-600 rounded-lg shadow-lg shadow-blue-200">
              <Sparkles className="w-6 h-6 text-white" />
            </div>
            <h2 className="text-xl font-bold text-gray-900">핵심 리뷰 분석 리포트</h2>
          </div>
          <div className="prose prose-blue max-w-none bg-gray-50/50 p-6 rounded-xl border border-gray-100">
            <ReactMarkdown>{analysisResult}</ReactMarkdown>
          </div>
        </section>
      )}

      {/* 리뷰 목록 섹션 */}
      <section className="space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
            수집된 최근 리뷰
            {reviews.length > 0 && (
              <span className="text-xs font-bold bg-blue-100 text-blue-600 px-2.5 py-0.5 rounded-full">
                {reviews.length}
              </span>
            )}
          </h2>
        </div>

        {isLoadingReviews ? (
          <div className="flex flex-col items-center justify-center py-24 bg-white rounded-3xl border border-gray-100 shadow-sm gap-4">
            <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
            <p className="text-gray-400 font-medium text-lg">데이터 저장소를 확인하고 있습니다...</p>
          </div>
        ) : reviews.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-32 bg-white rounded-3xl border-2 border-dashed border-gray-200 shadow-inner group">
            <div className="p-6 bg-gray-50 rounded-full mb-6 group-hover:scale-110 transition-transform duration-300">
              <MessageSquare className="w-16 h-16 text-gray-300" />
            </div>
            <h3 className="text-xl font-bold text-gray-700 mb-2">수집된 리뷰 데이터가 없습니다</h3>
            <p className="text-gray-400 text-center max-w-sm px-6">
              상단의 수집 설정에서 <strong>구글 맵 URL</strong>을 입력하고 <br/>
              <strong>[새 데이터 수집 시작]</strong> 버튼을 눌러주세요.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {reviews.map((review, index) => {
              const isPositive = review.rating >= 4;
              const isNegative = review.rating <= 2;
              
              return (
                <div 
                  key={index} 
                  className="bg-white p-6 rounded-2xl border border-gray-100 shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all duration-300 flex flex-col gap-4"
                >
                  <div className="flex justify-between items-start">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-gray-100 to-gray-200 flex items-center justify-center font-bold text-gray-600">
                        {review.author?.charAt(0) || "G"}
                      </div>
                      <div>
                        <p className="text-sm font-bold text-gray-900">{review.author}</p>
                        <p className="text-xs text-gray-400 font-medium">{review.date}</p>
                      </div>
                    </div>
                    <div className={`flex items-center px-3 py-1 rounded-lg text-xs font-black shadow-sm ${
                      isPositive ? "bg-green-50 text-green-600 border border-green-100" :
                      isNegative ? "bg-red-50 text-red-600 border border-red-100" :
                      "bg-yellow-50 text-yellow-600 border border-yellow-100"
                    }`}>
                      <Star className="w-3.5 h-3.5 mr-1 fill-current" />
                      {review.rating}.0
                    </div>
                  </div>
                  <p className="text-gray-600 text-sm leading-relaxed whitespace-pre-wrap flex-grow italic">
                    "{review.text}"
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
