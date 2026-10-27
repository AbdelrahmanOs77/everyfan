import { useEffect, useRef, useState } from 'react';
export type Screen = 'match' | 'perspectives' | 'insights' | 'lab' | 'feed';
const screens: Screen[] = ['match', 'perspectives', 'insights', 'lab', 'feed'];
const currentScreen = (): Screen => {
  const candidate = location.hash.slice(2) as Screen;
  return screens.includes(candidate) ? candidate : 'match';
};
export function useNavigation() {
  const [view, setView] = useState(currentScreen);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const scrollPositions = useRef(new Map<Screen, number>());
  const previous = useRef(view);
  useEffect(() => {
    if (!location.hash.startsWith('#/')) history.replaceState(null, '', '#/match');
    const change = () => {
      scrollPositions.current.set(previous.current, window.scrollY);
      const next = currentScreen();
      previous.current = next;
      setView(next);
    };
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      headingRef.current?.focus({ preventScroll: true });
      window.scrollTo({ top: scrollPositions.current.get(view) || 0, behavior: 'instant' });
    });
    document.title = `${view === 'lab' ? 'Judge Lab' : view.charAt(0).toUpperCase() + view.slice(1)} · EveryFan`;
    return () => cancelAnimationFrame(frame);
  }, [view]);
  const navigate = (screen: Screen) => {
    if (screen !== view) location.hash = `/${screen}`;
  };
  return { view, navigate, headingRef };
}
export const screenCopy = {
  en: {
    match: 'Match',
    perspectives: 'Perspectives',
    insights: 'Insights',
    lab: 'Judge Lab',
    feed: 'Overlay feed',
    tagline: 'One match. Millions of stories.',
    currentMatch: 'Current match',
    exploreInsights: 'Explore the match insights',
    synchronized: 'One clock. Four points of view.',
    measuredOnly: 'Measured facts from the match engine.',
    eyebrow: {
      match: 'THE MATCHROOM',
      perspectives: 'A DIFFERENT WAY TO SEE IT',
      insights: 'BEHIND THE PLAY',
      lab: 'PUT IT TO THE TEST',
      feed: 'THE PUBLISHED RECORD',
    },
    titles: {
      match: 'Your front-row seat.',
      perspectives: 'Same moment. Different stories.',
      insights: 'Read the shape of the game.',
      lab: 'See trust in action.',
      feed: 'Every story, backed by evidence.',
    },
    descriptions: {
      match: 'Follow the action. Make the commentary yours.',
      perspectives: 'Compare how one verified play is explained for different fans.',
      insights: 'Explore the measured context behind every turning point.',
      lab: 'Try the recorded demo, start a live run, or challenge the Verifier.',
      feed: 'Browse the published commentary and inspect the facts behind it.',
    },
  },
  ar: {
    match: 'المباراة',
    perspectives: 'المنظورات',
    insights: 'الإحصاءات',
    lab: 'مختبر التحقق',
    feed: 'موجز التعليقات',
    tagline: 'مباراة واحدة. ملايين القصص.',
    currentMatch: 'المباراة الحالية',
    exploreInsights: 'استكشف إحصاءات المباراة',
    synchronized: 'توقيت واحد. أربع وجهات نظر.',
    measuredOnly: 'حقائق مقاسة من محرك المباراة.',
    eyebrow: {
      match: 'غرفة المباراة',
      perspectives: 'شاهدها بطريقتك',
      insights: 'خلف أحداث المباراة',
      lab: 'جرّب بنفسك',
      feed: 'سجل التعليقات المنشورة',
    },
    titles: {
      match: 'مقعدك في الصف الأول.',
      perspectives: 'لحظة واحدة. قصص مختلفة.',
      insights: 'اقرأ ملامح المباراة.',
      lab: 'شاهد التحقق في العمل.',
      feed: 'كل قصة تستند إلى دليل.',
    },
    descriptions: {
      match: 'تابع اللعب واختر التعليق الذي يناسبك.',
      perspectives: 'قارن شرح الحدث الموثّق نفسه من زوايا مختلفة.',
      insights: 'استكشف السياق المقاس وراء اللحظات الحاسمة.',
      lab: 'شاهد التسجيل، أو ابدأ بثًا مباشرًا، أو اختبر المدقّق.',
      feed: 'تصفّح التعليقات المنشورة وافحص الحقائق وراءها.',
    },
  },
};
