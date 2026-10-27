import { useState } from 'react';
import { ArrowUpRight, FlaskConical, Play, Radio, ShieldCheck } from 'lucide-react';
import { copy } from '../i18n';
import type { Language, Preferences } from '../types';
import { BreakExperiment } from './Dialogs';
export function JudgeLab({
  language,
  preference,
  matchId,
  momentId,
  demoReady,
  connecting,
  onDemo,
  onLive,
}: {
  language: Language;
  preference: Preferences;
  matchId: string;
  momentId?: string;
  demoReady: boolean;
  connecting: boolean;
  onDemo: () => void;
  onLive: () => void;
}) {
  const [experiment, setExperiment] = useState(0);
  const t = copy[language];
  const ar = language === 'ar';
  return (
    <div className="lab-page">
      <div className="lab-actions">
        <article className="lab-action">
          <span className="lab-icon">
            <Play />
          </span>
          <span className="eyebrow">{ar ? 'ابدأ من هنا' : 'START HERE'}</span>
          <h2>{t.demo}</h2>
          <p>
            {ar
              ? 'استكشف مباراة مسجلة بتعليقات الوكلاء المعتمدة. استمتع بالعرض دون استهلاك النماذج.'
              : 'Explore a recorded match with approved agent commentary. Ready to watch, with no model cost.'}
          </p>
          <button className="primary-button" disabled={!demoReady || connecting} onClick={onDemo}>
            {t.demo}
            <ArrowUpRight size={18} />
          </button>
        </article>
        <article className="lab-action">
          <span className="lab-icon">
            <Radio />
          </span>
          <span className="eyebrow">{ar ? 'الوكلاء مباشرة' : 'AGENTS IN ACTION'}</span>
          <h2>{t.live}</h2>
          <p>
            {ar
              ? 'ابدأ بثًا مشتركًا يتحكم فيه المضيف. تخضع استدعاءات النماذج للميزانية والحدود المتاحة.'
              : 'Start a shared broadcast controlled by its host. Model calls use the available live budget and limits.'}
          </p>
          <button className="secondary-button" disabled={!momentId || connecting} onClick={onLive}>
            {connecting ? t.connecting : t.live}
            <ArrowUpRight size={18} />
          </button>
        </article>
        <article className="lab-action">
          <span className="lab-icon">
            <FlaskConical />
          </span>
          <span className="eyebrow">{ar ? 'تحدّ المدقّق' : 'CHALLENGE THE VERIFIER'}</span>
          <h2>{t.break}</h2>
          <p>
            {ar
              ? 'أدخل رقمًا غير موثّق وشاهد كيف يُرفض قبل الوصول إلى البث. اختبار مجاني بلا استدعاء نموذج.'
              : 'Introduce an unsupported number. See it rejected before it reaches the broadcast. No model call required.'}
          </p>
          <button
            className="secondary-button"
            disabled={!momentId}
            onClick={() => setExperiment((n) => n + 1)}
          >
            {experiment ? (ar ? 'أعد الاختبار' : 'Run again') : t.break}
            <ArrowUpRight size={18} />
          </button>
        </article>
      </div>
      <section className="lab-workbench" aria-label={t.verifier}>
        <div className="section-heading">
          <div>
            <span className="eyebrow">
              {ar ? 'من المسودة إلى البث' : 'FROM DRAFT TO BROADCAST'}
            </span>
            <h2>{experiment ? t.verifier : ar ? 'تحدّ المدقّق.' : 'Challenge the Verifier.'}</h2>
          </div>
          <ShieldCheck size={22} />
        </div>
        {experiment && momentId ? (
          <BreakExperiment
            key={`${matchId}-${experiment}-${language}`}
            language={language}
            preference={preference}
            matchId={matchId}
            momentId={momentId}
          />
        ) : (
          <div className="lab-empty">
            <ShieldCheck size={38} />
            <h3>
              {ar
                ? 'يبدأ التعليق الجدير بالثقة بالأدلة.'
                : 'Trustworthy commentary starts with evidence.'}
            </h3>
            <p>
              {ar
                ? 'اختر «اختبر التحقق» لمقارنة المسودة المرفوضة بالبديل الموثّق.'
                : 'Choose Break it to compare a rejected draft with its verified replacement.'}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
