import React, { useEffect, useState, useRef } from "react";
import { analyzeReviews } from "../services/geminiService";
import { Sparkles, Star, Loader2, AlertCircle, Settings, Link as LinkIcon, Calendar, Play, Info, MessageSquare, Search, CheckCircle2 } from "lucide-react";
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

  // 수집 관련 상태
  const [targetUrl, setTargetUrl] = useState<string>("");
  const [startDate, setStartDate] = useState<string>("");
  const [isCollecting, setIsCollecting] = useState<boolean>(false);
  const [expectedMinutes, setExpectedMinutes] = useState<number>(3);
  const pollingInterval = useRef<NodeJS.Timeout | null>(null);

  // 데이터 불러오기 함수 (중복 사용을 위해 분리)
  const fetchReviews = async (showLoading = true) => {
    if (showLoading) setIsLoadingReviews(true);
    try {
      // 캐시 방지를 위한 타임스탬프 추가 (?t=...)
      const response = await fetch(`/data/reviews.json?t=${new Date().getTime()}`);
      if (!response.ok) return;
      
      const data = await response.json();
      // 샘플 데이터 및 빈 데이터 필터링
      const validData = (data || []).filter((r: Review) => 
        r.author !== "김철수" && r.author !== "이영희" && r.author !== "박민수"
      );

      if (validData.length > 0) {
        setReviews(validData);
        if (isCollecting) {
          setIsCollecting(false);
          if (pollingInterval.current) clearInterval(pollingInterval.current);
          alert("✅ 수집이 완료되었습니다! 새로운 리뷰를 확인하세요.");
        }
      }
    } catch (err) {
      console.error("데이터 로드 실패:", err);
    } finally {
      if (showLoading) setIsLoadingReviews(false);
    }
  };

  useEffect(() => {
    fetchReviews();
    return () => { if (pollingInterval.current) clearInterval(pollingInterval.current); };
  }, []);

  // AI 분석 실행
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

  // 수집 시작 및 자동 감지(Polling) 시작
  const handleStartCollection = () => {
    if (!targetUrl || !startDate) return;

    // 기간에 따른 예상 시간 및 게이지 속도 계산
    const diffTime = Math.abs(new Date().getTime() - new Date(startDate).getTime());
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    
    let duration = 180; 
    let mins = 3;

    if (diffDays <= 7) { duration = 60; mins = 1; }
    else if (diffDays <= 31) { duration = 150; mins = 2.5; }
    else if (diffDays <= 365) { duration = 360; mins = 6; }
    else { duration = 600; mins = 10; }

    setExpectedMinutes(mins);
    document.documentElement.style.setProperty('--collect-duration', `${duration}s`);
    setIsCollecting(true);
    setReviews([]); // 이전 데이터 초기화

    // 자동 감지 루틴 시작 (15초마다 서버 확인)
    pollingInterval.current = setInterval(() => {
      fetchReviews(false);
    }, 15000);
    
    // 실제 GitHub Action 호출 로직은 여기에 위치 (현재는 UI 시뮬레이션 상태)
    console.log("Collection started for:", targetUrl);
  };

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-8 font-sans bg-gray-50/30 min-h-screen">
      {/* 헤더 */}
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-gray-200">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 tracking-tight flex items-center gap-2">
            구글 맵 리뷰 분석 대시보드
          </h1>
          <p className="text-gray-500 mt-2 text-sm">매장 URL을 입력하여 고객의 목소리를 실시간으로 분석하세요.</p>
        </div>
        <button
          onClick={handleAnalyze}
          disabled={isAnalyzing || reviews.length === 0 || isCollecting}
          className="inline-flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white font-bold rounded-xl hover:bg-blue-700 transition-all disabled:opacity-50 disabled:bg-gray-300 shadow-lg hover:shadow-blue-200"
        >
          {isAnalyzing ? <Loader2 className="w-5 h-5 animate-spin" /> : <Sparkles className="w-5 h-5" />}
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
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-6">
          <div className="space-y-3">
            <label className="text-sm font-bold text-gray-700 flex items-center gap-2">
              <LinkIcon className="w-4 h-4 text-blue-500" />
              구글 맵 매장 URL
            </label>
            <input 
              type="url" 
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              placeholder="주소를 복사해서 붙여넣어 주세요" 
              className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:bg-white outline-none transition-all text-sm"
            />
            <div className="bg-blue-50/30 p-3 rounded-lg border border-blue-100">
              <p className="text-[10px] font-black text-blue-400 uppercase tracking-widest mb-1">허용되는 주소 형식</p>
              <ul className="text-[12px] text-gray-500 space-y-1">
                <li className="flex gap-2"><strong>단축:</strong> <span>https://maps.app.goo.gl/XXXX</span></li>
                <li className="flex gap-2"><strong>상세:</strong> <span className="truncate">https://www.google.com/maps/place/...</span></li>
              </ul>
            </div>
          </div>
          <div className="space-y-3">
            <label className="text-sm font-bold text-gray-700 flex items-center gap-2">
              <Calendar className="w-4 h-4 text-blue-500" />
              수집 시작일 기준
            </label>
            <input 
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:bg-white outline-none transition-all text-sm text-gray-700"
            />
            <div className="p-3 bg-amber-50 rounded-lg border border-amber-100">
              <p className="text-[11px] text-amber-700 leading-relaxed font-medium">
                <strong>⏳ 예상 소요 시간:</strong> {startDate ? (Math.ceil(Math.abs(new Date().getTime() - new Date(startDate).getTime()) / (1000 * 60 * 60 * 24)) > 30 ? "약 5분 이상" : "약 2분 내외") : "-"} <br/>
                기간이 길거나 리뷰가 많을수록 스캔 시간이 늘어납니다.
              </p>
            </div>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 pt-6 border-t border-gray-100">
          <div className="flex items-start gap-3 text-sm text-gray-600 bg-gray-50 p-4 rounded-xl flex-1">
            <Info className="w-5 h-5 text-blue-500 flex-shrink-0 mt-0.5" />
            <p className="leading-relaxed">
              수집을 시작하면 AI 일꾼이 구글 맵을 스캔합니다. <span className="font-bold text-blue-700">이 창을 끄지 말고 잠시만 기다려주세요.</span> 완료 시 자동으로 목록이 업데이트됩니다.
            </p>
          </div>
          <button 
            onClick={handleStartCollection}
            disabled={isCollecting || !targetUrl || !startDate}
            className={`inline-flex items-center justify-center gap-3 px-10 py-4 font-black rounded-xl transition-all shadow-xl active:scale-95 ${
              isCollecting ? "bg-amber-500 text-white" : "bg-gray-900 text-white hover:bg-black"
            }`}
          >
            {isCollecting ? <Loader2 className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5 fill-current" />}
            {isCollecting ? "데이터 수집 및 확인 중..." : "새 데이터 수집 시작"}
          </button>
        </div>
      </section>

      {/* 분석 리포트 */}
      {analysisResult && (
        <section className="bg-white p-8 rounded-3xl border-2 border-blue-100 shadow-2xl animate-in fade-in zoom-in-95 duration-500">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-blue-600 rounded-lg shadow-lg">
              <Sparkles className="w-6 h-6 text-white" />
            </div>
            <h2 className="text-xl font-bold text-gray-900">핵심 리뷰 분석 리포트</h2>
          </div>
          <div className="prose prose-blue max-w-none bg-blue-50/30 p-6 rounded-2xl border border-blue-50">
            <ReactMarkdown>{analysisResult}</ReactMarkdown>
          </div>
        </section>
      )}

      {/* 리뷰 목록 */}
      <section className="space-y-6">
        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
          수집된 최근 리뷰
          {reviews.length > 0 && <span className="text-xs font-bold bg-blue-100 text-blue-600 px-3 py-1 rounded-full">{reviews.length}건</span>}
        </h2>

        {isCollecting ? (
          <div className="flex flex-col items-center justify-center py-32 bg-white rounded-3xl border-2 border-blue-100 shadow-sm relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-blue-50/20 to-transparent animate-shimmer" />
            <div className="relative z-10 flex flex-col items-center">
              <div className="relative mb-8">
                <Search className="w-16 h-16 text-blue-500 animate-bounce" />
                <Loader2 className="w-24 h-24 text-blue-50/50 animate-spin absolute -top-4 -left-4" />
              </div>
              <h3 className="text-2xl font-black text-gray-800 mb-3">리뷰를 긁어오고 있습니다</h3>
              <p className="text-gray-400 text-center text-sm leading-relaxed">
                현재 일꾼이 구글 맵 페이지를 한 땀 한 땀 스캔하고 있습니다.<br/>
                예상 대기 시간: <strong>약 {expectedMinutes}분</strong> (완료 시 자동 업데이트)
              </p>
              
              <div className="mt-10 w-80 h-3 bg-gray-100 rounded-full overflow-hidden border border-gray-100">
                <div 
                  className="h-full bg-blue-500 shadow-[0_0_15px_rgba(59,130,246,0.6)]" 
                  style={{ animation: `progress var(--collect-duration) linear forwards` }} 
                />
              </div>
              <div className="mt-6 flex items-center gap-2 text-blue-500 font-bold text-xs animate-pulse">
                <div className="w-2 h-2 bg-blue-500 rounded-full" />
                서버 응답 확인 중...
              </div>
            </div>
          </div>
        ) : isLoadingReviews ? (
          <div className="flex flex-col items-center justify-center py-24 bg-white rounded-3xl border border-gray-100 shadow-sm gap-4">
            <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
            <p className="text-gray-400 font-medium">저장소를 확인하고 있습니다...</p>
          </div>
        ) : reviews.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-32 bg-white rounded-3xl border-2 border-dashed border-gray-200 shadow-inner">
            <div className="p-8 bg-gray-50 rounded-full mb-6">
              <MessageSquare className="w-16 h-16 text-gray-200" />
            </div>
            <h3 className="text-xl font-bold text-gray-700 mb-2">아직 데이터가 없습니다</h3>
            <p className="text-gray-400 text-center text-sm max-w-sm px-8 leading-relaxed">
              상단 설정에서 <strong>매장 URL</strong>과 <strong>날짜</strong>를 입력하고<br/>
              <strong>[새 데이터 수집 시작]</strong>을 클릭하면 분석이 시작됩니다.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {reviews.map((review, index) => (
              <div key={index} className="bg-white p-6 rounded-2xl border border-gray-100 shadow-sm hover:shadow-2xl hover:-translate-y-1.5 transition-all duration-300 flex flex-col gap-4">
                <div className="flex justify-between items-start">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-gray-100 flex items-center justify-center font-black text-gray-400">{review.author?.charAt(0)}</div>
                    <div><p className="text-sm font-bold text-gray-900">{review.author}</p><p className="text-[10px] text-gray-400 font-bold uppercase tracking-tighter">{review.date}</p></div>
                  </div>
                  <div className={`flex items-center px-3 py-1 rounded-lg text-xs font-black shadow-sm ${review.rating >= 4 ? "bg-green-50 text-green-600 border border-green-100" : review.rating <= 2 ? "bg-red-50 text-red-600 border border-red-100" : "bg-yellow-50 text-yellow-600 border border-yellow-100"}`}>
                    <Star className="w-3.5 h-3.5 mr-1 fill-current" />{review.rating}.0
                  </div>
                </div>
                <p className="text-gray-600 text-[13px] leading-relaxed italic flex-grow">"{review.text}"</p>
              </div>
            ))}
          </div>
        )}
      </section>

      <style>{`
        @keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
        .animate-shimmer { animation: shimmer 2.5s infinite linear; }
        @keyframes progress { 0% { width: 0%; } 100% { width: 97%; } }
        :root { --collect-duration: 180s; }
      `}</style>
    </div>
  );
}
