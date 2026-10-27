import { useEffect, useRef, useState } from 'react';
export type Screen = 'beginner' | 'tactical' | 'player' | 'club' | 'perspectives' | 'lab' | 'feed';
export const isFanScreen = (view: Screen): view is 'beginner' | 'tactical' | 'player' | 'club' =>
  ['beginner', 'tactical', 'player', 'club'].includes(view);
const screens: Screen[] = ['beginner', 'tactical', 'player', 'club', 'perspectives', 'lab', 'feed'];
const currentScreen = (): Screen => {
  const raw = location.hash.slice(2);
  const candidate = (
    raw === 'match' ? 'beginner' : raw === 'insights' ? 'tactical' : raw
  ) as Screen;
  return screens.includes(candidate) ? candidate : 'beginner';
};
export function useNavigation() {
  const [view, setView] = useState(currentScreen);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const scrollPositions = useRef(new Map<Screen, number>());
  const previous = useRef(view);
  useEffect(() => {
    if (location.hash !== `#/${currentScreen()}`)
      history.replaceState(null, '', `#/${currentScreen()}`);
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
    beginner: 'Beginner',
    tactical: 'Tactical',
    player: 'Player',
    club: 'My club',
    perspectives: 'Perspectives',
    lab: 'Judge Lab',
    feed: 'Overlay feed',
    tagline: 'One match. Millions of stories.',
    currentMatch: 'Current match',
    exploreInsights: 'Explore the match insights',
    synchronized: 'One clock. Four points of view.',
    measuredOnly: 'Measured facts from the match engine.',
    eyebrow: {
      beginner: 'THE GAME, MADE CLEAR',
      tactical: 'THE ANALYST DESK',
      player: 'YOUR PLAYER. EVERY DETAIL.',
      club: 'FROM YOUR SIDE OF THE STANDS',
      perspectives: 'A DIFFERENT WAY TO SEE IT',
      lab: 'PUT IT TO THE TEST',
      feed: 'THE PUBLISHED RECORD',
    },
    titles: {
      beginner: 'Enjoy the game. Understand the play.',
      tactical: 'Look beyond the scoreline.',
      player: 'Follow the player you came for.',
      club: 'Your club. Your matchday.',
      perspectives: 'Same moment. Different stories.',
      lab: 'See trust in action.',
      feed: 'Every story, backed by evidence.',
    },
    descriptions: {
      beginner: 'Simple match facts, plain-language stories, and a little help along the way.',
      tactical: 'Pressure, progression, territory, passing connections and shot evidence.',
      player: 'Individual contributions, physical performance and moments that matter.',
      club: 'Club-focused commentary and the measured story of your side.',
      perspectives: 'Compare how one verified play is explained for different fans.',
      lab: 'Try the recorded demo, start a live run, or challenge the Verifier.',
      feed: 'Browse the published commentary and inspect the facts behind it.',
    },
  },
  ar: {
    beginner: 'للمبتدئ',
    tactical: 'تكتيكي',
    player: 'اللاعب',
    club: 'ناديك',
    perspectives: 'المنظورات',
    lab: 'مختبر التحقق',
    feed: 'موجز التعليقات',
    tagline: 'مباراة واحدة. ملايين القصص.',
    currentMatch: 'المباراة الحالية',
    exploreInsights: 'استكشف إحصاءات المباراة',
    synchronized: 'توقيت واحد. أربع وجهات نظر.',
    measuredOnly: 'حقائق مقاسة من محرك المباراة.',
    eyebrow: {
      beginner: 'اللعبة ببساطة',
      tactical: 'مكتب المحلل',
      player: 'لاعبك. كل التفاصيل.',
      club: 'من مدرجات ناديك',
      perspectives: 'شاهدها بطريقتك',
      lab: 'جرّب بنفسك',
      feed: 'سجل التعليقات المنشورة',
    },
    titles: {
      beginner: 'استمتع بالمباراة وافهم أحداثها.',
      tactical: 'انظر إلى ما وراء النتيجة.',
      player: 'تابع اللاعب الذي جئت من أجله.',
      club: 'ناديك. يوم مباراتك.',
      perspectives: 'لحظة واحدة. قصص مختلفة.',
      lab: 'شاهد التحقق في العمل.',
      feed: 'كل قصة تستند إلى دليل.',
    },
    descriptions: {
      beginner: 'حقائق بسيطة وتعليقات واضحة وشرح يساعدك على المتابعة.',
      tactical: 'الضغط والتقدم والسيطرة الميدانية وروابط التمرير وأدلة التسديد.',
      player: 'مساهمات اللاعب وأداؤه البدني ولحظاته البارزة.',
      club: 'تعليق لناديك وقصة فريقك من الحقائق المقاسة.',
      perspectives: 'قارن شرح الحدث الموثّق نفسه من زوايا مختلفة.',
      lab: 'شاهد التسجيل، أو ابدأ بثًا مباشرًا، أو اختبر المدقّق.',
      feed: 'تصفّح التعليقات المنشورة وافحص الحقائق وراءها.',
    },
  },
};
