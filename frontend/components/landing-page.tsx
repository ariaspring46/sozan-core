import {
  ArrowLeft,
  Boxes,
  Check,
  ChevronDown,
  CreditCard,
  ImageIcon,
  Inbox,
  Instagram,
  MessageCircle,
  PackageSearch,
  Send,
  ShieldCheck,
  Sparkles,
  Store,
  type LucideIcon,
} from "lucide-react";
import { LandingPhone } from "@/components/landing-phone";
import { LandingSloganRotator } from "@/components/landing-slogan-rotator";
import { SozanMark } from "@/components/sozan-mark";
import { SozanOrb } from "@/components/sozan-orb";
import { money } from "@/lib/digits";
import { loadPublicPlans, type PublicPlan } from "@/lib/public-plans";

/** سه کار اصلی که در صفحه با ماکت نشان داده می‌شوند. */
const CHAPTERS = [
  {
    n: "۰۱",
    id: "shop",
    kicker: "ساخت فروشگاه",
    title: "چت می‌کنی؛ فروشگاه را می‌بینی.",
    body: "رنگ، حس و بخش‌ها را در چت می‌گویی. سوزان پیش از ساخت می‌پرسد و با «بساز» فروشگاه چند دقیقه‌ای آماده می‌شود. بعد روی هر قسمت صفحه بزن و بگو چه عوض شود؛ اگر خوشت نیامد، با «برگشت» به نسخهٔ قبل برمی‌گردی.",
  },
  {
    n: "۰۲",
    id: "studio",
    kicker: "استودیوی محتوا",
    title: "پست و کپشن، از همان چت.",
    body: "بگو برای کدام کالا؛ سوزان عکس پست و کپشن جدا برای اینستاگرام، تلگرام و واتساپ آماده می‌کند. عکس را دانلود کن و در پیجت بگذار، یا با تأیید خودت به کانال تلگرام، شمارهٔ واتساپ یا دایرکت اینستاگرام بفرست.",
  },
  {
    n: "۰۳",
    id: "panel",
    kicker: "صندوق و فروش",
    title: "از سؤال مشتری تا پرداخت، یک گفتگو.",
    body: "پیام مشتری‌های اینستاگرام و تلگرام یک‌جا می‌آید. سوزان با لحن خودت جواب را آماده می‌کند و اگر کالا قیمت داشته باشد، لینک پرداخت را هم کنارش می‌گذارد.",
  },
] as const;

const STEPS = [
  { n: "۱", title: "با شمارهٔ موبایل وارد شو", body: "کد پیامکی می‌آید؛ نه رمز لازم است، نه کارت بانکی." },
  { n: "۲", title: "از کسب‌وکارت بگو", body: "نام پیج یا کانالت را بده، یا کالاها را با عکس و قیمت اضافه کن." },
  { n: "۳", title: "در چت بگو چه می‌خواهی", body: "فروشگاه، پست و جواب مشتری از همان گفتگو جلو می‌رود؛ کار مهم فقط با تأیید تو." },
] as const;

const CAPABILITIES: readonly { icon: LucideIcon; title: string; body: string; tags: readonly string[] }[] = [
  {
    icon: Store,
    title: "فروشگاه با چند جمله",
    body: "حس، رنگ و کالاهایت را می‌گویی؛ سوزان فروشگاه را روی نشانی اختصاصی می‌سازد و دامنهٔ خودت را هم می‌توانی وصل کنی.",
    tags: ["بدون کدنویسی", "ویرایش روی خود صفحه", "دامنهٔ شخصی"],
  },
  {
    icon: PackageSearch,
    title: "کالا از پیج و کانالت",
    body: "اگر پیج اینستاگرام یا کانال تلگرامت عمومی باشد، سوزان پست‌ها را می‌خواند و نام، قیمت و عکس کالاها را برمی‌دارد؛ هر کالا را هم می‌توانی خودت با عکس و قیمت اضافه کنی.",
    tags: ["عکس واقعی کالا", "افزودن دستی", "بدون کالای ساختگی"],
  },
  {
    icon: ImageIcon,
    title: "استودیوی محتوا",
    body: "برای هر کالا عکس پست و کپشن جداگانهٔ هر کانال می‌گیری؛ دانلودش می‌کنی یا با تأیید خودت می‌فرستی.",
    tags: ["عکس پست", "کپشن هر کانال", "فقط با تأیید تو"],
  },
  {
    icon: Inbox,
    title: "صندوق پیام مشتری",
    body: "دایرکت اینستاگرام و پیام تلگرام یک‌جا می‌آید. جواب را خودت می‌دهی، سوزان با لحن تو پیش‌نویس می‌کند، یا خودکار جواب می‌دهد و هر وقت لازم بود کار را به تو می‌سپارد.",
    tags: ["لحن خودت", "پیش‌نویس هوشمند", "جواب خودکار"],
  },
  {
    icon: CreditCard,
    title: "سفارش و پرداخت",
    body: "لینک پرداخت کنار جواب مشتری می‌آید. با درگاه زرین‌پال یا آیدی‌پی خودت پول مستقیم به حسابت می‌رود؛ بدون درگاه هم کارت‌به‌کارت با رسید یا درگاه سوزان در دسترس است.",
    tags: ["زرین‌پال", "آیدی‌پی", "کارت‌به‌کارت با رسید"],
  },
  {
    icon: Boxes,
    title: "انبار و فروش روزانه",
    body: "کالا، قیمت و موجودی را یک‌جا نگه می‌داری؛ فروش فروشگاه و دایرکت کنار فروش‌های دستی‌ات ثبت می‌شود.",
    tags: ["قیمت و موجودی", "ثبت فروش", "کیف پول"],
  },
];

const CHANNELS: readonly { icon: LucideIcon; name: string; lead: string; body: string; can: readonly string[] }[] = [
  {
    icon: Instagram,
    name: "اینستاگرام",
    lead: "ورود رسمی، بدون پسورد",
    body: "دایرکت مشتری به صندوق می‌آید و محتوا به دایرکت مخاطب فرستاده می‌شود. پیج عمومی هم با نام کاربری برای پیدا کردن کالاها خوانده می‌شود.",
    can: ["دایرکت مشتری", "ارسال محتوا", "خواندن پیج عمومی"],
  },
  {
    icon: Send,
    name: "تلگرام",
    lead: "با بات تلگرام",
    body: "پیام مشتری از بات می‌آید و پست استودیو در کانالت منتشر می‌شود. کانال عمومی هم برای پیدا کردن کالاها خوانده می‌شود.",
    can: ["پیام مشتری", "پست در کانال", "خواندن کانال عمومی"],
  },
  {
    icon: MessageCircle,
    name: "واتساپ",
    lead: "حساب رسمی کسب‌وکار",
    body: "پست استودیو به شمارهٔ مقصدی که تعیین می‌کنی فرستاده می‌شود. پیام بیرون از پنجرهٔ ۲۴ ساعتهٔ واتساپ به قالب تأییدشده نیاز دارد.",
    can: ["ارسال محتوا به شماره"],
  },
];

const LEGAL = [
  { href: "/about", label: "درباره ما" },
  { href: "/contact", label: "تماس با ما" },
  { href: "/terms", label: "قوانین و مقررات" },
  { href: "/refund", label: "لغو اشتراک و بازگشت وجه" },
] as const;

const NAV = [
  { href: "#capabilities", label: "امکانات" },
  { href: "#how", label: "نحوهٔ کار" },
  { href: "#channels", label: "کانال‌ها" },
  { href: "#plans", label: "پلن‌ها" },
  { href: "#faq", label: "پرسش‌ها" },
] as const;

const ENAMAD_SEAL =
  "<a referrerpolicy='origin' target='_blank' href='https://trustseal.enamad.ir/?id=7802913&Code=BEQkRB0rcIHAGmJ82IQQXg9fuhGocmZL'><img referrerpolicy='origin' src='https://trustseal.enamad.ir/logo.aspx?id=7802913&Code=BEQkRB0rcIHAGmJ82IQQXg9fuhGocmZL' alt='' style='cursor:pointer' code='BEQkRB0rcIHAGmJ82IQQXg9fuhGocmZL'></a>";

const FAQS = [
  {
    q: "پسورد اینستاگرام را می‌گیرید؟",
    a: "نه. اینستاگرام با ورود رسمی وصل می‌شود و هیچ رمزی نزد سوزان نمی‌ماند.",
  },
  {
    q: "برای ساخت فروشگاه باید کدنویسی بلد باشم؟",
    a: "نه. در چت می‌گویی چه می‌خواهی؛ سوزان می‌پرسد، می‌سازد و هر تغییری را هم با حرف زدن انجام می‌دهی.",
  },
  {
    q: "پیجم خصوصی است یا سوزان کالایی پیدا نکرد؛ چه کنم؟",
    a: "کالاها را با عکس و قیمت در انبار اضافه کن یا عکسشان را در چت بفرست. اگر هنوز قیمت نگذاشته‌ای، فروشگاه را «بدون قیمت» بساز تا مشتری قیمت را بپرسد.",
  },
  {
    q: "فروشگاهم روی چه نشانی بالا می‌آید؟",
    a: "اول روی یک نشانی اختصاصی در سوزان، مثل nam.sozan-core.ir. دامنهٔ خودت را هم هر وقت خواستی وصل می‌کنی.",
  },
  {
    q: "بعد از ساخت چه چیزهایی را می‌توانم عوض کنم؟",
    a: "روی هر قسمت صفحه بزن و بگو چه عوض شود: متن، عکس، رنگ، حس یا یک بخش تازه. اگر نتیجه را نخواستی، به نسخهٔ قبل برمی‌گردی.",
  },
  {
    q: "پول مشتری به کجا می‌رود؟",
    a: "با درگاه زرین‌پال یا آیدی‌پی خودت، مستقیم به حساب خودت و بدون کارمزد سوزان. اگر درگاه نداری، می‌توانی پرداخت کارت‌به‌کارت با رسید بگیری یا از درگاه سوزان با ۲٪ کارمزد استفاده کنی و مانده را به شبای خودت برداشت کنی.",
  },
  {
    q: "سوزان بدون اجازهٔ من چیزی منتشر می‌کند؟",
    a: "نه. انتشار محتوا، ساخت فروشگاه و هر تغییر مهم اول از تو تأیید می‌گیرد. محتوای ساخته‌شده در استودیو می‌ماند تا خودت بخواهی.",
  },
  {
    q: "جواب خودکار به مشتری در کدام پلن است؟",
    a: "در پلن رایگان جواب را خودت می‌دهی؛ پرو با لحن خودت پیش‌نویس آماده می‌کند و پرو مکس می‌تواند همان جواب را خودکار بفرستد.",
  },
  {
    q: "پیامک ورود و اطلاع سفارش چطور حساب می‌شود؟",
    a: "پیامک از زیرساخت سوزان می‌رود. هر پلن سهمیهٔ ماهانه دارد و پیامک بیشتر از سهمیه از کیف پولت کم می‌شود.",
  },
] as const;

function Kicker({ children }: { children: React.ReactNode }) {
  return (
    <p className="sozan-glass inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-[12.5px] font-medium text-warm">
      <span className="h-1.5 w-1.5 rounded-full bg-accent shadow-[0_0_10px_2px_rgb(var(--c-accent)/0.7)]" />
      {children}
    </p>
  );
}

function PlanCard({ plan, start, until, paymentReady }: { plan: PublicPlan; start: string; until: string; paymentReady: boolean }) {
  const featured = plan.id === "pro";
  const discounted = plan.listPrice > plan.price && plan.price > 0;
  const paymentLater = plan.checkout === "open" && !paymentReady;
  const specs = [
    plan.channels ? `${money(plan.channels)} کانال` : plan.channels === 0 ? "همهٔ کانال‌ها" : "",
    plan.smsQuota ? `${money(plan.smsQuota)} پیامک در ماه` : "",
    plan.workspaces && plan.workspaces > 1 ? `${money(plan.workspaces)} فضای کاری` : "",
  ].filter(Boolean);
  const action =
    plan.checkout === "soon" || paymentLater ? (
      <span className="mt-auto inline-flex h-12 items-center justify-center rounded-full border border-line/70 px-4 text-center text-sm text-ink/65">
        {paymentLater ? "پرداخت به‌زودی فعال می‌شود" : "به‌زودی"}
      </span>
    ) : (
      <a
        href={start}
        className={`mt-auto inline-flex h-12 items-center justify-center rounded-full px-6 text-sm font-bold ${
          featured ? "landing-cta" : "sozan-glass text-ink hover:border-accent/50"
        }`}
      >
        {plan.checkout === "free" ? "رایگان شروع کن" : `انتخاب ${plan.label}`}
      </a>
    );
  return (
    <article className={`landing-lift relative flex min-h-[25rem] flex-col rounded-[1.75rem] p-6 ${featured ? "sozan-card shadow-[0_0_60px_-18px_rgb(var(--c-accent)/0.6)]" : "sozan-glass"}`}>
      {featured ? (
        <span className="landing-cta absolute -top-3 end-6 rounded-full px-3 py-1 text-xs font-bold">پیشنهاد سوزان</span>
      ) : null}
      <h3 className="landing-display text-2xl">{plan.label}</h3>
      <div className="mt-4">
        {discounted ? <p className="text-sm text-ink/55 line-through">{money(plan.listPrice)} تومان</p> : null}
        <p className="landing-display text-[1.7rem]">{plan.price > 0 ? `${money(plan.price)} تومان` : "رایگان"}</p>
        <p className="mt-1 text-xs text-warm">
          {plan.price > 0 ? "ماهانه" : "بدون پرداخت"}
          {plan.discountPercent ? ` · ٪${money(plan.discountPercent)} تخفیف` : ""}
          {discounted && until ? ` تا ${until}` : ""}
        </p>
      </div>
      {specs.length ? <p className="mt-4 rounded-xl bg-ink/5 px-3 py-2 text-xs leading-6 text-ink/80">{specs.join(" · ")}</p> : null}
      <ul className="mt-5 space-y-3 text-sm text-ink/85">
        {plan.features.map((item) => (
          <li key={item} className="flex items-start gap-2.5">
            <Check size={16} className="mt-1 shrink-0 text-warm" aria-hidden />
            <span className="leading-7">{item}</span>
          </li>
        ))}
      </ul>
      <div className="mt-6 flex flex-1 flex-col">{action}</div>
    </article>
  );
}

function ShopMock() {
  return (
    <div className="sozan-card overflow-hidden rounded-[1.6rem]">
      <div className="flex items-center gap-1.5 border-b border-ink/10 px-4 py-3">
        <span className="h-2 w-2 rounded-full bg-ink/20" />
        <span className="h-2 w-2 rounded-full bg-ink/20" />
        <span className="h-2 w-2 rounded-full bg-ink/20" />
        <span className="mx-auto rounded-full bg-ink/5 px-3 py-1 text-[10px] text-ink/55" dir="ltr">
          mina.sozan-core.ir
        </span>
      </div>
      <div className="p-4">
        <div className="landing-swatch flex h-24 flex-col items-start justify-end rounded-xl p-3">
          <p className="text-sm font-bold text-ink">کالکشن پاییز رسید</p>
          <span className="mt-1.5 rounded-full bg-accentStrong px-3 py-1 text-[10px] text-onAccent">دیدن کالاها</span>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2">
          {[
            ["پیراهن کتان", "۸۹۰"],
            ["کیف چرمی", "۱٬۲۵۰"],
            ["شال پشمی", "۴۲۰"],
          ].map(([name, price]) => (
            <div key={name} className="rounded-xl bg-ink/5 p-1.5">
              <div className="landing-swatch h-14 rounded-lg" />
              <p className="mt-1.5 truncate text-[10px] text-ink/80">{name}</p>
              <p className="text-[10px] text-warm">{price} هزار</p>
            </div>
          ))}
        </div>
        <div className="sozan-glass mt-3 flex items-center gap-2 rounded-full px-3 py-2 text-[11px] text-ink/80">
          <Sparkles size={13} className="text-warm" aria-hidden />
          «دکمه‌ها را زرشکی کن»
        </div>
      </div>
    </div>
  );
}

function StudioMock() {
  return (
    <div className="sozan-card overflow-hidden rounded-[1.6rem] p-4">
      <div className="landing-swatch relative grid aspect-[4/5] max-h-56 w-full place-items-center rounded-xl">
        <span className="rounded-full bg-[rgb(var(--c-chatbg)/0.6)] px-3 py-1 text-[11px] text-ink backdrop-blur">انگشتر نقرهٔ دست‌ساز</span>
      </div>
      <div className="mt-3 flex gap-1.5 text-[10.5px]">
        {["اینستاگرام", "تلگرام", "واتساپ"].map((ch, i) => (
          <span key={ch} className={`rounded-full px-3 py-1 ${i === 0 ? "sozan-tile" : "bg-ink/5 text-ink/70"}`}>
            {ch}
          </span>
        ))}
      </div>
      <p className="mt-3 text-[11.5px] leading-6 text-ink/80">هر قطعه با دقت ساخته می‌شود؛ هدیه‌ای که حس گرمش می‌ماند. برای سفارش دایرکت بده.</p>
      <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
        <span className="sozan-glass rounded-full py-2 text-center text-ink/85">دانلود</span>
        <span className="landing-cta rounded-full py-2 text-center font-bold">بفرست</span>
      </div>
    </div>
  );
}

function PanelMock() {
  return (
    <div className="sozan-card overflow-hidden rounded-[1.6rem] p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-bold text-ink">پیام مشتری‌ها</p>
        <span className="rounded-full bg-accent/20 px-2.5 py-0.5 text-[10px] text-warm">۲ تازه</span>
      </div>
      <div className="mt-3 space-y-2">
        {[
          { name: "سارا", text: "این انگشتر سایز ۵۴ دارید؟", ch: "اینستاگرام", fresh: true },
          { name: "امیر", text: "ارسال به شیراز چند روزه؟", ch: "تلگرام", fresh: true },
          { name: "نگار", text: "ممنون، رسید.", ch: "اینستاگرام", fresh: false },
        ].map((m) => (
          <div key={m.name} className="flex items-center gap-2.5 rounded-xl bg-ink/5 p-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/20 text-[11px] font-bold text-warm">{m.name.slice(0, 1)}</span>
            <span className="min-w-0 flex-1">
              <span className="block text-[11px] font-bold text-ink">
                {m.name} <span className="font-normal text-muted">· {m.ch}</span>
              </span>
              <span className="block truncate text-[11px] text-ink/70">{m.text}</span>
            </span>
            {m.fresh ? <span className="h-2 w-2 shrink-0 rounded-full bg-accent" /> : null}
          </div>
        ))}
      </div>
      <div className="sozan-ai mt-3 rounded-2xl p-3 text-[11px] leading-6">
        <p className="text-[10px] text-warm">پیش‌نویس سوزان برای سارا</p>
        <p className="text-ink/90">سلام سارا جان! بله، سایز ۵۴ موجود است و ۸۵۰ هزار تومان.</p>
        <span className="mt-2 inline-flex items-center gap-1 rounded-full bg-accent/20 px-2.5 py-0.5 text-[10px] text-warm">
          <CreditCard size={11} aria-hidden />
          لینک پرداخت
        </span>
      </div>
    </div>
  );
}

function ChapterVisual({ id }: { id: string }) {
  if (id === "shop") return <ShopMock />;
  if (id === "studio") return <StudioMock />;
  return <PanelMock />;
}

export async function LandingPage({ panelOrigin }: { panelOrigin: string }) {
  const catalog = await loadPublicPlans();
  const plans = catalog?.plans ?? [];
  const start = panelOrigin ? `${panelOrigin.replace(/\/$/, "")}/login` : "/login";

  return (
    <div className="sozan-landing min-h-dvh overflow-x-hidden text-ink">
      <link rel="preload" href="/fonts/estedad-arabic.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
      <link rel="preload" href="/fonts/estedad-latin.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:end-4 focus:top-4 focus:z-50 focus:rounded-xl focus:bg-accent focus:px-4 focus:py-2 focus:text-onAccent"
      >
        رفتن به محتوا
      </a>
      <header className="landing-nav sticky top-0 z-40 border-b border-ink/10 bg-[rgb(var(--c-chatbg)/0.72)] backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-5 sm:px-8">
          <a href="#main" className="flex min-h-11 items-center gap-2.5">
            <SozanMark className="h-9 w-9" glow={false} />
            <span className="font-sozan text-base font-extrabold text-ink">سوزان</span>
          </a>
          <nav className="hidden items-center gap-7 text-sm text-ink/70 md:flex" aria-label="بخش‌های صفحه">
            {NAV.map((item) => (
              <a key={item.href} className="inline-flex min-h-11 items-center transition-colors hover:text-ink" href={item.href}>
                {item.label}
              </a>
            ))}
            <details className="relative">
              <summary className="inline-flex min-h-11 cursor-pointer list-none items-center marker:content-none hover:text-ink">شرکت</summary>
              <div className="sozan-glass absolute end-0 top-10 z-50 w-56 rounded-2xl p-3 text-sm shadow-card">
                {LEGAL.map((item) => (
                  <a key={item.href} className="flex min-h-11 items-center text-ink/85 hover:text-ink" href={item.href}>
                    {item.label}
                  </a>
                ))}
              </div>
            </details>
          </nav>
          <div className="flex items-center gap-2">
            <details className="landing-nav-menu relative md:hidden">
              <summary className="sozan-glass inline-flex min-h-11 cursor-pointer list-none items-center rounded-full px-4 text-sm text-ink marker:content-none">
                بخش‌ها
              </summary>
              <div className="sozan-glass absolute end-0 top-12 z-50 w-56 rounded-2xl p-3 text-sm shadow-card">
                {NAV.map((item) => (
                  <a key={item.href} className="flex min-h-11 items-center text-ink/85 hover:text-ink" href={item.href}>
                    {item.label}
                  </a>
                ))}
                {LEGAL.map((item) => (
                  <a key={item.href} className="flex min-h-11 items-center text-ink/70 hover:text-ink" href={item.href}>
                    {item.label}
                  </a>
                ))}
              </div>
            </details>
            <a href={start} className="landing-cta inline-flex min-h-11 items-center rounded-full px-5 text-sm font-bold">
              ورود
            </a>
          </div>
        </div>
      </header>

      <main id="main">
        <section className="landing-hero sozan-chat relative overflow-hidden">
          <div className="relative z-10 mx-auto grid max-w-6xl items-center gap-12 px-5 pb-16 pt-10 sm:px-8 lg:grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)] lg:gap-10 lg:pb-24 lg:pt-16">
            <div className="landing-hero-copy">
              <div className="landing-fade landing-fade-kicker mb-6">
                <Kicker>دستیار فروش برای فروشنده‌های ایرانی</Kicker>
              </div>
              <LandingSloganRotator />
              <p className="landing-fade landing-fade-body landing-lede mt-7 max-w-xl text-base leading-8 sm:text-lg sm:leading-9">
                فقط بگو چه می‌خواهی. سوزان با کالاهای خودت فروشگاه اینترنتی می‌سازد، برای اینستاگرام و تلگرام پست و کپشن آماده می‌کند، در جواب دادن به مشتری کنارت است و سفارش و پرداخت را یک‌جا نگه می‌دارد.
              </p>
              <div className="landing-fade landing-fade-cta mt-9 flex flex-wrap items-center gap-3">
                <a href={start} className="landing-cta inline-flex h-12 items-center justify-center gap-2 rounded-full px-7 text-[15px] font-bold">
                  رایگان شروع کن
                  <ArrowLeft size={18} aria-hidden />
                </a>
                <a href="#how" className="sozan-glass inline-flex h-12 items-center rounded-full px-6 text-sm text-ink/90 transition-colors hover:text-ink">
                  ببین چطور کار می‌کند
                </a>
              </div>
              <ul className="landing-fade landing-fade-cta mt-7 flex flex-wrap items-center gap-2 text-[12.5px] text-ink/80">
                {["ورود رسمی؛ بدون پسورد اینستاگرام", "پلن رایگان برای شروع", "بدون کدنویسی"].map((item) => (
                  <li key={item} className="flex items-center gap-1.5 rounded-full bg-ink/5 px-3 py-1.5">
                    <ShieldCheck size={14} className="text-warm" aria-hidden />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
            <LandingPhone />
          </div>
        </section>

        <section className="border-y border-ink/10">
          <div className="mx-auto grid max-w-6xl grid-cols-3 gap-2 px-4 py-6 sm:gap-3 sm:px-8 sm:py-8">
            {[
              ["یک گفتگو", "فروشگاه، محتوا، پیام مشتری و فروش"],
              ["سه کانال", "اینستاگرام، تلگرام و واتساپ"],
              ["بدون کدنویسی", "همه‌چیز با حرف زدن و چند لمس"],
            ].map(([title, body]) => (
              <div key={title} className="sozan-glass rounded-2xl px-3 py-4 text-center sm:px-5 sm:py-5 sm:text-start">
                <p className="sozan-title-glow landing-display text-[15px] sm:text-xl">{title}</p>
                <p className="mt-1 text-[11.5px] leading-5 text-ink/70 sm:mt-1.5 sm:text-sm sm:leading-7">{body}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="capabilities" className="relative mx-auto max-w-6xl scroll-mt-20 px-5 py-16 sm:px-8 sm:py-24">
          <div className="max-w-3xl">
            <Kicker>همهٔ چرخهٔ فروش</Kicker>
            <h2 className="landing-display mt-4 text-[clamp(1.9rem,4vw,3.2rem)] leading-snug">
              فقط سایت‌ساز نیست؛ <span className="sozan-title-glow">همکار روزانهٔ فروشگاهت</span> است.
            </h2>
            <p className="landing-lede mt-5 text-base leading-8">
              از آوردن کالا تا ساخت ویترین، محتوا، جواب مشتری، گرفتن پول و کنترل موجودی؛ هر بخش به بخش بعدی وصل است.
            </p>
          </div>
          <div className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {CAPABILITIES.map((item) => {
              const Icon = item.icon;
              return (
                <article key={item.title} className="sozan-card landing-lift flex flex-col rounded-[1.6rem] p-6 sm:min-h-[17rem]">
                  <span className="sozan-tile flex h-11 w-11 items-center justify-center rounded-2xl">
                    <Icon size={21} aria-hidden />
                  </span>
                  <h3 className="landing-display mt-5 text-xl leading-8">{item.title}</h3>
                  <p className="landing-lede mt-2.5 text-sm leading-7">{item.body}</p>
                  <ul className="mt-auto hidden flex-wrap gap-2 pt-5 sm:flex">
                    {item.tags.map((tag) => (
                      <li key={tag} className="rounded-full bg-ink/5 px-3 py-1 text-xs text-ink/75">
                        {tag}
                      </li>
                    ))}
                  </ul>
                </article>
              );
            })}
          </div>
        </section>

        <section id="how" className="relative scroll-mt-20 border-t border-ink/10">
          <div className="landing-section-glow pointer-events-none absolute inset-x-0 top-0 h-96" aria-hidden />
          <div className="relative mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24">
            <Kicker>محصول را ببین</Kicker>
            <h2 className="landing-display mt-4 max-w-3xl text-[clamp(1.9rem,4vw,3.2rem)] leading-snug">سه گفتگوی اصلی؛ از ایده تا فروش.</h2>
            <div className="mt-12 space-y-16 sm:space-y-24">
              {CHAPTERS.map((item, i) => (
                <article key={item.id} id={item.id} className="grid items-center gap-8 lg:grid-cols-[1.05fr_0.95fr] lg:gap-16">
                  <div className={i % 2 === 1 ? "lg:order-2" : ""}>
                    <p className="flex items-center gap-3 text-sm font-medium text-warm">
                      <span className="sozan-tile grid h-9 w-9 place-items-center rounded-xl text-xs font-bold">{item.n}</span>
                      {item.kicker}
                    </p>
                    <h3 className="landing-display mt-4 text-[clamp(1.7rem,3.6vw,2.8rem)] leading-snug">{item.title}</h3>
                    <p className="landing-lede mt-4 text-base leading-8">{item.body}</p>
                  </div>
                  <div className={`relative mx-auto w-full max-w-sm ${i % 2 === 1 ? "lg:order-1" : ""}`} aria-hidden>
                    <span className="sozan-halo pointer-events-none absolute -inset-10 rounded-full opacity-60" />
                    <div className="relative">
                      <ChapterVisual id={item.id} />
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="px-5 sm:px-8">
          <div className="sozan-card relative mx-auto flex max-w-6xl flex-col items-start justify-between gap-6 overflow-hidden rounded-[2rem] px-6 py-9 sm:flex-row sm:items-center sm:px-10">
            <span className="sozan-halo pointer-events-none absolute -left-20 -top-24 h-72 w-72 rounded-full" aria-hidden />
            <div className="relative">
              <p className="landing-display text-[clamp(1.4rem,2.8vw,2rem)]">کسب‌وکارت را به سوزان معرفی کن.</p>
              <p className="landing-lede mt-2 text-sm">از پلن رایگان شروع کن؛ اولین فروشگاهت را در چت بساز.</p>
            </div>
            <a href={start} className="landing-cta relative inline-flex h-12 items-center justify-center gap-2 rounded-full px-7 text-sm font-bold">
              ساخت حساب رایگان
              <ArrowLeft size={17} aria-hidden />
            </a>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24">
          <Kicker>شروع ساده</Kicker>
          <h2 className="landing-display mt-4 text-[clamp(1.8rem,4vw,2.8rem)]">سه قدم تا اولین فروشگاه</h2>
          <ol className="relative mt-10 grid gap-4 sm:grid-cols-3">
            {STEPS.map((step) => (
              <li key={step.n} className="sozan-glass rounded-[1.6rem] p-6">
                <span className="landing-cta grid h-11 w-11 place-items-center rounded-full font-sozan text-lg font-extrabold">{step.n}</span>
                <h3 className="mt-4 text-lg font-bold">{step.title}</h3>
                <p className="landing-lede mt-2 text-sm leading-7">{step.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="channels" className="scroll-mt-20 border-y border-ink/10">
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24">
            <div className="max-w-3xl">
              <Kicker>کانال‌ها</Kicker>
              <h2 className="landing-display mt-4 text-[clamp(1.9rem,4vw,3.1rem)] leading-snug">مشتری هرجا هست، کار تو یک‌جا می‌ماند.</h2>
              <p className="landing-lede mt-5 text-base leading-8">هر کانال توانایی متفاوتی دارد و سوزان دقیق نشان می‌دهد هر حساب برای چه کاری وصل است.</p>
            </div>
            <div className="mt-10 grid gap-4 md:grid-cols-3">
              {CHANNELS.map((channel) => {
                const Icon = channel.icon;
                return (
                  <article key={channel.name} className="sozan-glass landing-lift flex flex-col rounded-[1.6rem] p-6">
                    <div className="flex items-center gap-3">
                      <span className="sozan-tile grid h-11 w-11 place-items-center rounded-2xl">
                        <Icon size={20} aria-hidden />
                      </span>
                      <div>
                        <h3 className="landing-display text-lg">{channel.name}</h3>
                        <p className="text-xs text-warm">{channel.lead}</p>
                      </div>
                    </div>
                    <p className="landing-lede mt-4 text-sm leading-7">{channel.body}</p>
                    <ul className="mt-auto flex flex-wrap gap-2 pt-5">
                      {channel.can.map((item) => (
                        <li key={item} className="flex items-center gap-1 rounded-full bg-ink/5 px-3 py-1 text-xs text-ink/80">
                          <Check size={12} className="text-signal" aria-hidden />
                          {item}
                        </li>
                      ))}
                    </ul>
                  </article>
                );
              })}
            </div>
          </div>
        </section>

        <section id="plans" className="relative scroll-mt-20">
          <div className="landing-section-glow pointer-events-none absolute inset-x-0 top-0 h-96" aria-hidden />
          <div className="relative mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24">
            <div className="max-w-3xl">
              <Kicker>پلن‌ها</Kicker>
              <h2 className="landing-display mt-4 text-[clamp(1.9rem,4vw,3.1rem)] leading-snug">رایگان شروع کن؛ وقتی کارت بیشتر شد ارتقا بده.</h2>
              <p className="landing-lede mt-5 text-base leading-8">پلن‌ها در تعداد کانال، سهمیهٔ پیامک و خودکار بودن جواب مشتری فرق دارند.</p>
            </div>
            <div className="mt-12 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {plans.map((plan) => (
                <PlanCard key={plan.id} plan={plan} start={start} until={catalog?.discountUntilLabel || ""} paymentReady={catalog?.paymentReady === true} />
              ))}
            </div>
            {plans.length === 0 ? <p className="mt-6 text-sm text-ink/70">قیمت پلن‌ها الان در دسترس نیست.</p> : null}
            <p className="mt-6 text-xs leading-6 text-ink/55">
              مبلغ روی کارت همان مبلغ پرداخت است و اشتراک ماهانه است.
              {catalog?.discountUntilLabel ? ` تخفیف تا ${catalog.discountUntilLabel}.` : ""}
            </p>
          </div>
        </section>

        <section id="faq" className="mx-auto max-w-6xl scroll-mt-20 px-5 py-16 sm:px-8 sm:py-24">
          <Kicker>پرسش‌ها</Kicker>
          <h2 className="landing-display mt-4 text-[clamp(1.8rem,4vw,2.8rem)]">قبل از شروع چه باید بدانی؟</h2>
          <div className="mt-10 grid gap-3 md:grid-cols-2">
            {FAQS.map((item) => (
              <details key={item.q} className="landing-faq sozan-glass group self-start rounded-2xl px-5">
                <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-3 py-3 text-[15px] font-medium text-ink/90 hover:text-ink">
                  {item.q}
                  <ChevronDown size={18} className="landing-chev shrink-0 text-warm transition-transform" aria-hidden />
                </summary>
                <p className="landing-lede pb-5 text-sm leading-7">{item.a}</p>
              </details>
            ))}
          </div>
        </section>

        <section className="sozan-chat relative overflow-hidden border-t border-ink/10">
          <div className="relative mx-auto flex max-w-3xl flex-col items-center px-5 py-20 text-center sm:px-8 sm:py-28">
            <div className="relative grid place-items-center">
              <span className="sozan-halo pointer-events-none absolute -inset-10 rounded-full" aria-hidden />
              <SozanOrb size={128} className="relative" />
            </div>
            <p className="mt-6 text-sm font-medium text-warm">بگو، بساز، بفروش</p>
            <h2 className="landing-display mt-3 text-[clamp(2rem,5vw,3.4rem)] leading-snug">
              فروشگاهت را از همین امروز <span className="sozan-title-glow">یک‌جا اداره کن.</span>
            </h2>
            <p className="landing-lede mt-5 text-base leading-8">فقط با شمارهٔ موبایل وارد شو؛ پلن رایگان برای ساخت اولین فروشگاه آماده است.</p>
            <a href={start} className="landing-cta mt-8 inline-flex h-12 items-center justify-center gap-2 rounded-full px-8 text-[15px] font-bold">
              رایگان شروع کن
              <ArrowLeft size={18} aria-hidden />
            </a>
          </div>
        </section>
      </main>

      <footer className="border-t border-ink/10">
        <div className="mx-auto grid max-w-6xl gap-8 px-5 py-10 sm:grid-cols-[1fr_auto_auto] sm:items-center sm:px-8">
          <div>
            <div className="flex items-center gap-2.5">
              <SozanMark className="h-8 w-8" glow={false} />
              <p className="font-sozan text-base font-extrabold">سوزان</p>
            </div>
            <p className="mt-3 max-w-sm text-sm leading-6 text-ink/70">فروشگاه، محتوا، پیام مشتری و پرداخت برای فروشندهٔ ایرانی.</p>
          </div>
          <nav aria-label="پیوندهای پایین صفحه" className="flex flex-wrap gap-x-5 text-sm text-ink/75">
            {NAV.slice(0, 4).map((item) => (
              <a key={item.href} href={item.href} className="inline-flex min-h-11 min-w-11 items-center justify-center hover:text-warm">
                {item.label}
              </a>
            ))}
            {LEGAL.map((item) => (
              <a key={item.href} href={item.href} className="inline-flex min-h-11 min-w-11 items-center justify-center hover:text-warm">
                {item.label}
              </a>
            ))}
            <a href={panelOrigin || "https://app.sozan-core.ir"} className="inline-flex min-h-11 min-w-11 items-center justify-center hover:text-warm">
              ورود به پنل
            </a>
          </nav>
          <div className="flex items-center gap-4">
            <div dangerouslySetInnerHTML={{ __html: ENAMAD_SEAL }} />
            <span className="text-xs leading-5 text-ink/60">
              دارای نماد
              <br />
              اعتماد الکترونیکی
            </span>
          </div>
        </div>
        <div className="border-t border-ink/10">
          <p className="mx-auto max-w-6xl px-5 py-4 text-center text-xs leading-6 text-ink/60 sm:px-8">ساخته شده توسط شرکت گهر شبکه کارمانیا</p>
        </div>
      </footer>
    </div>
  );
}
