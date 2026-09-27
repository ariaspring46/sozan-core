import { LandingSloganRotator } from "@/components/landing-slogan-rotator";
import { SozanMark } from "@/components/sozan-mark";
import { money } from "@/lib/digits";
import { loadPublicPlans, type PublicPlan } from "@/lib/public-plans";

const CHAPTERS = [
  {
    n: "۰۱",
    id: "shop",
    kicker: "ساخت سایت",
    title: "چت می‌کنی؛ سایت را می‌بینی.",
    body: "از رنگ و حس تا ویژگی‌ها، همه را در چت می‌گویی. «بساز» را که بزنی، سایت آماده می‌شود؛ روی هر قسمت که کلیک کنی، می‌گویی چه عوض شود.",
  },
  {
    n: "۰۲",
    id: "studio",
    kicker: "استودیو",
    title: "پست را از همان چت بفرست.",
    body: "کپشن اینستاگرام، تلگرام و واتساپ در همان چت نوشته می‌شود؛ عکس و فیلم را هم همان‌جا می‌بینی. حساب‌ها را که وصل کنی، پست را می‌فرستی: تلگرام در کانالت، اینستاگرام دایرکت مخاطب انتخاب‌شده، واتساپ به همان شماره‌ای که گذاشته‌ای.",
  },
  {
    n: "۰۳",
    id: "panel",
    kicker: "صندوق و فروش",
    title: "از سؤال مشتری تا پرداخت، یک گفتگو.",
    body: "پیام مشتری از تلگرام و اینستاگرام یک‌جا می‌آید. سوزان با لحن خودت جواب را آماده می‌کند و اگر کالا قیمت داشته باشد، لینک پرداخت را هم کنار پاسخ می‌گذارد.",
  },
] as const;

const STEPS = [
  { n: "۱", title: "وارد شو", body: "با شماره موبایل و کد پیامک وارد پنل می‌شوی." },
  { n: "۲", title: "کانالت را معرفی کن", body: "سوزان کالا و لحن برندت را از ویترین فعلی می‌شناسد." },
  { n: "۳", title: "در چت بگو چه می‌خواهی", body: "فروشگاه، پست و پاسخ مشتری را از همان پنل جلو می‌بری." },
] as const;

const CAPABILITIES = [
  {
    n: "۰۱",
    title: "فروشگاه از دل چت",
    body: "حس، رنگ و ویژگی‌ها را می‌گویی؛ سوزان فروشگاه واقعی را روی نشانی اختصاصی می‌سازد و دامنهٔ خودت هم قابل اتصال است.",
    tags: ["ساخت بدون کدنویسی", "ویرایش روی پیش‌نمایش", "دامنهٔ شخصی"],
  },
  {
    n: "۰۲",
    title: "کالا از ویترین فعلی",
    body: "پست‌های عمومی اینستاگرام یا تلگرام خوانده می‌شوند تا نام، قیمت، رنگ، سایز و عکس واقعی کالاها وارد فروشگاه شود.",
    tags: ["بدون کالای ساختگی", "عکس واقعی پست", "دسته‌بندی و موجودی"],
  },
  {
    n: "۰۳",
    title: "استودیوی محتوای چندکاناله",
    body: "برای هر کانال کپشن جدا می‌گیری، تصویر و ویدیو را در همان گفتگو می‌بینی و بعد از تأیید منتشر می‌کنی.",
    tags: ["اینستاگرام", "تلگرام", "واتساپ"],
  },
  {
    n: "۰۴",
    title: "صندوق همهٔ گفتگوها",
    body: "پیام مشتری‌های تلگرام و اینستاگرام یک‌جا می‌آید؛ جواب را دستی، به‌شکل پیش‌نویس یا خودکار و با لحن خودت می‌فرستی.",
    tags: ["لحن برند", "پیش‌نویس هوشمند", "پاسخ خودکار"],
  },
  {
    n: "۰۵",
    title: "فروش، پرداخت و کیف پول",
    body: "سوزان لینک پرداخت را کنار پاسخ مشتری می‌گذارد، فروش آنلاین را ثبت می‌کند و برداشت مانده با شبای فروشنده انجام می‌شود.",
    tags: ["لینک پرداخت کوتاه", "زرین‌پال و آیدی‌پی", "برداشت با شبا"],
  },
  {
    n: "۰۶",
    title: "انبار و عملیات روزانه",
    body: "کالا، قیمت و موجودی را مدیریت می‌کنی؛ فروش‌های فروشگاه و دایرکت کنار ثبت دستی فروش دیده می‌شوند.",
    tags: ["قیمت و موجودی", "فروش کانال‌ها", "یک پنل"],
  },
] as const;

const CHANNELS = [
  {
    name: "اینستاگرام",
    lead: "ویترین، محتوا و دایرکت",
    body: "اسکن ویترین عمومی با نام کاربری؛ انتشار محتوا و دریافت دایرکت با اتصال رسمی صفحه.",
  },
  {
    name: "تلگرام",
    lead: "کانال، پست و گفتگو",
    body: "خواندن ویترین عمومی و ارسال پست یا پاسخ مشتری با بات رسمی تلگرام که خودت می‌سازی.",
  },
  {
    name: "واتساپ",
    lead: "محتوا برای مخاطب مشخص",
    body: "ارسال از رابط رسمی واتساپ به شمارهٔ مقصد؛ پیام‌های خارج از پنجرهٔ ۲۴ساعته به قالب تأییدشده نیاز دارند.",
  },
] as const;

const LEGAL = [
  { href: "/about", label: "درباره ما" },
  { href: "/contact", label: "تماس با ما" },
  { href: "/terms", label: "قوانین و مقررات" },
  { href: "/refund", label: "لغو اشتراک و بازگشت وجه" },
] as const;

const ENAMAD_SEAL =
  "<a referrerpolicy='origin' target='_blank' href='https://trustseal.enamad.ir/?id=7802913&Code=BEQkRB0rcIHAGmJ82IQQXg9fuhGocmZL'><img referrerpolicy='origin' src='https://trustseal.enamad.ir/logo.aspx?id=7802913&Code=BEQkRB0rcIHAGmJ82IQQXg9fuhGocmZL' alt='' style='cursor:pointer' code='BEQkRB0rcIHAGmJ82IQQXg9fuhGocmZL'></a>";

const FAQS = [
  {
    q: "پسورد اینستاگرام را می‌گیرید؟",
    a: "نه. اتصال هر حساب از مسیر رسمی همان سرویس انجام می‌شود و پسوردی نزد ما نمی‌ماند.",
  },
  {
    q: "برای ساخت سایت باید کد بلد باشم؟",
    a: "نه. فقط در چت می‌گویی چه می‌خواهی؛ سوزان می‌سازد.",
  },
  {
    q: "فروشگاهم روی چه آدرسی بالا می‌آید؟",
    a: "اول روی آدرس سوزان. دامنه‌ی خودت را که بخواهی، به همان وصل می‌کنی.",
  },
  {
    q: "بعد از ساخت، چه چیزهایی می‌توانم عوض کنم؟",
    a: "هر قسمت از صفحه را که کلیک کنی، همان‌جا می‌گویی چه عوض شود؛ از رنگ و حس تا متن‌ها.",
  },
  {
    q: "برای گرفتن پول حتماً درگاه شخصی لازم دارم؟",
    a: "نه. اگر مرچنت زرین‌پال یا آیدی‌پی خودت را داشته باشی، پول مستقیم به حساب خودت می‌رود و سوزان کمیسیون نمی‌گیرد. در غیر این صورت می‌توانی از درگاه سوزان استفاده کنی؛ دو درصد کمیسیون کم می‌شود و مانده با شبا قابل برداشت است.",
  },
  {
    q: "سوزان خودش بدون اجازه پست منتشر می‌کند؟",
    a: "نه. ساخت و انتشار از چت و با تأیید خودت است. تصویر و ویدیوی ساخته‌شده در استودیو می‌ماند.",
  },
  {
    q: "پاسخ خودکار مشتری روی کدام پلن است؟",
    a: "در رایگان پاسخ دستی است؛ پرو پیش‌نویس هوشمند می‌دهد و پرو مکس می‌تواند همان پاسخ را با لحن برندت خودکار ارسال کند.",
  },
  {
    q: "پیامک ورود و سفارش از کجا می‌رود؟",
    a: "پیامک از زیرساخت سوزان ارسال می‌شود. هر پلن سهمیهٔ ماهانه دارد و مصرف بیشتر از سهمیه از کیف پول کم می‌شود.",
  },
] as const;

function PlanCard({ plan, start, until }: { plan: PublicPlan; start: string; until: string }) {
  const featured = plan.id === "pro";
  const discounted = plan.listPrice > plan.price && plan.price > 0;
  const action =
    plan.checkout === "soon" ? (
      <span className="mt-auto inline-flex h-12 items-center justify-center rounded-full border border-line/80 px-6 text-sm text-ink/50">به‌زودی</span>
    ) : (
      <a
        href={start}
        className={`mt-auto inline-flex h-12 items-center justify-center rounded-full px-6 text-sm ${
          featured ? "bg-accent text-onAccent hover:bg-warm" : "border border-line/80 text-ink hover:border-warm/60"
        }`}
      >
        {plan.checkout === "free" ? "رایگان شروع کن" : `انتخاب ${plan.label}`}
      </a>
    );
  return (
    <article
      className={`relative flex min-h-[24rem] flex-col rounded-3xl border p-6 ${
        featured ? "border-accent/70 bg-accent/[0.08]" : "border-line/50 bg-canvas/70"
      }`}
    >
      {featured ? (
        <span className="absolute -top-3 end-6 rounded-full bg-accent px-3 py-1 text-[11px] text-onAccent">پیشنهاد سوزان</span>
      ) : null}
      <h3 className="landing-display text-2xl">{plan.label}</h3>
      <div className="mt-4">
        {discounted ? <p className="text-sm text-ink/40 line-through">{money(plan.listPrice)} تومان</p> : null}
        <p className="landing-display text-2xl">{plan.price > 0 ? `${money(plan.price)} تومان` : "رایگان"}</p>
        {plan.discountPercent ? <p className="mt-1 text-xs text-warm">٪{money(plan.discountPercent)} تخفیف</p> : null}
        <p className="mt-1 text-xs text-warm">{plan.price > 0 ? "ماهانه" : "بدون پرداخت"}</p>
        {discounted && until ? <p className="mt-1 text-xs text-ink/60">تا {until}</p> : null}
      </div>
      <ul className="mt-6 space-y-3 border-t border-line/50 pt-6 text-sm text-ink/80">
        {plan.features.map((item) => (
          <li key={item} className="flex items-start gap-3">
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-warm" />
            <span className="leading-7">{item}</span>
          </li>
        ))}
      </ul>
      {action}
    </article>
  );
}

function ShopMock() {
  return (
    <div className="landing-demo-card relative p-4">
      <div className="flex items-center gap-1.5 border-b border-line/40 pb-3">
        <span className="h-1.5 w-1.5 rounded-full bg-ink/25" />
        <span className="h-1.5 w-1.5 rounded-full bg-ink/25" />
        <span className="h-1.5 w-1.5 rounded-full bg-ink/25" />
        <span className="mx-auto rounded-full bg-ink/5 px-3 py-1 text-[10px] text-ink/45">frooshgah-man.ir</span>
      </div>
      <div className="pt-4">
        <div className="landing-tile flex h-16 items-center justify-between rounded-lg px-4">
          <p className="text-xs font-medium text-ink/90">کالکشن پاییز رسید</p>
          <span className="rounded-full bg-accent px-3 py-1 text-[10px] text-onAccent">دیدن کالاها</span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {["پیراهن مردانه", "کیف چرمی", "کلاه بافت", "شال پشمی"].map((name) => (
            <div key={name} className="rounded-lg border border-line/40 bg-ink/5 p-1.5">
              <div className="landing-tile h-10 rounded-md" />
              <p className="mt-1.5 truncate text-[9px] text-ink/70">{name}</p>
              <p className="text-[9px] text-warm">نمونه · ۹۸۰ هزار</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StudioMock() {
  return (
    <div className="landing-demo-card relative p-4">
      <div className="flex items-center justify-between border-b border-line/40 pb-3">
        <p className="text-xs font-medium text-ink/85">پست تازه</p>
        <span className="sozan-breathe h-1.5 w-1.5 rounded-full bg-accent" />
      </div>
      <div className="pt-3">
        <div className="grid grid-cols-3 gap-2">
          <div className="landing-tile h-16 rounded-lg" />
          <div className="landing-tile h-16 rounded-lg" />
          <div className="flex h-16 items-center justify-center rounded-lg border border-dashed border-line/60 text-2xl font-light text-ink/35">
            +
          </div>
        </div>
        <div className="mt-4 space-y-2">
          <div className="landing-skeleton h-2 w-full" />
          <div className="landing-skeleton h-2 w-3/4" />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {["اینستاگرام", "تلگرام", "واتساپ"].map((ch, i) => (
            <span
              key={ch}
              className="flex items-center gap-1.5 rounded-full border border-line/50 bg-ink/5 px-3 py-1 text-[10px] text-ink/70"
            >
              <span className={`h-1.5 w-1.5 rounded-full ${i === 0 ? "bg-accent" : "bg-ink/30"}`} />
              {ch}
            </span>
          ))}
        </div>
        <div className="mt-4 flex justify-end">
          <span className="rounded-full bg-accent px-4 py-1.5 text-[11px] text-onAccent">پست را بفرست</span>
        </div>
      </div>
    </div>
  );
}

function PanelMock() {
  return (
    <div className="landing-demo-card relative p-4">
      <div className="flex items-center justify-between border-b border-line/40 pb-3">
        <p className="text-xs font-medium text-ink/85">پیام مشتری‌ها</p>
        <span className="rounded-full bg-accent/15 px-2.5 py-0.5 text-[10px] text-warm">۲ نو</span>
      </div>
      <div className="space-y-3 pt-3">
        {[
          { name: "سارا", unread: true },
          { name: "امیر", unread: true },
          { name: "نگار", unread: false },
        ].map((m) => (
          <div key={m.name} className="flex items-center gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-warm/40 bg-warm/10 text-[11px] text-warm">
              {m.name.slice(0, 1)}
            </span>
            <div className="flex-1 space-y-1.5">
              <div className={`landing-skeleton h-1.5 ${m.unread ? "w-4/5" : "w-3/5"}`} />
              <div className={`landing-skeleton h-1.5 ${m.unread ? "w-3/5" : "w-2/5"}`} />
            </div>
            {m.unread ? <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" /> : null}
          </div>
        ))}
      </div>
      <div className="mt-4 flex items-center gap-2 border-t border-line/40 pt-3 text-[10px] text-ink/60">
        <span className="flex items-center gap-1.5">
          <span className="h-1 w-1 rounded-full bg-warm/80" />
          ۳ سفارش تازه
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1 w-1 rounded-full bg-warm/80" />
          موجودی کم است
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
    <div className="sozan-landing min-h-screen overflow-x-hidden bg-canvas text-ink">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:end-4 focus:top-4 focus:z-50 focus:rounded-xl focus:bg-accent focus:px-4 focus:py-2 focus:text-onAccent"
      >
        رفتن به محتوا
      </a>
      <header className="landing-nav sticky top-0 z-40 border-b border-line/40 bg-canvas/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-5 sm:h-[4.25rem] sm:px-8">
          <a href="#main" className="flex items-center gap-3">
            <SozanMark className="h-9 w-9" glow={false} />
            <span className="text-sm font-medium text-warm">سوزان</span>
          </a>
          <nav className="hidden items-center gap-8 text-sm text-ink/70 md:flex">
            <a className="transition-colors hover:text-ink" href="#capabilities">
              امکانات
            </a>
            <a className="transition-colors hover:text-ink" href="#how">
              نحوهٔ کار
            </a>
            <a className="transition-colors hover:text-ink" href="#channels">
              کانال‌ها
            </a>
            <a className="transition-colors hover:text-ink" href="#plans">
              پلن‌ها
            </a>
            <details className="relative">
              <summary className="cursor-pointer list-none marker:content-none hover:text-ink">شرکت</summary>
              <div className="absolute end-0 top-8 z-50 w-56 rounded-2xl border border-line/70 bg-paper/95 p-3 text-sm shadow-card">
                {LEGAL.map((item) => (
                  <a key={item.href} className="block py-2 text-ink/80 hover:text-ink" href={item.href}>
                    {item.label}
                  </a>
                ))}
              </div>
            </details>
          </nav>
          <div className="flex items-center gap-3">
            <details className="landing-nav-menu relative md:hidden">
              <summary className="inline-flex h-10 cursor-pointer list-none items-center rounded-full border border-line/80 bg-paper/60 px-4 text-sm text-ink marker:content-none">
                بخش‌ها
              </summary>
              <div className="absolute end-0 top-11 z-50 w-44 rounded-2xl border border-line/70 bg-paper/95 p-3 text-sm shadow-card">
                <a className="block py-2 text-ink/80 hover:text-ink" href="#capabilities">
                  امکانات
                </a>
                <a className="block py-2 text-ink/80 hover:text-ink" href="#how">
                  نحوهٔ کار
                </a>
                <a className="block py-2 text-ink/80 hover:text-ink" href="#channels">
                  کانال‌ها
                </a>
                <a className="block py-2 text-ink/80 hover:text-ink" href="#plans">
                  پلن‌ها
                </a>
                {LEGAL.map((item) => (
                  <a key={item.href} className="block py-2 text-ink/80 hover:text-ink" href={item.href}>
                    {item.label}
                  </a>
                ))}
              </div>
            </details>
            <a
              href={start}
              className="inline-flex h-10 items-center rounded-full border border-line/80 bg-paper/60 px-4 text-sm text-ink hover:border-warm/50 hover:text-warm"
            >
              ورود
            </a>
          </div>
        </div>
      </header>

      <main id="main">
        <section className="landing-hero relative">
          <div className="landing-hero-glow pointer-events-none absolute inset-0" aria-hidden />
          <div className="relative z-10 mx-auto grid max-w-6xl items-center gap-6 px-5 pb-12 pt-10 sm:px-8 lg:grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)] lg:gap-10 lg:pb-28 lg:pt-16">
            <div className="landing-hero-copy">
              <p className="landing-fade landing-fade-kicker landing-kicker mb-5 font-medium text-warm">
                دستیار فروش برای کسب‌وکارهای ایرانی
              </p>
              <LandingSloganRotator />
              <p className="landing-fade landing-fade-body landing-lede mt-8 max-w-xl text-base leading-8 sm:text-lg sm:leading-9">
                سوزان از کالاهای واقعی پیجت فروشگاه می‌سازد، برای هر کانال محتوا آماده می‌کند، پیام مشتری را جواب می‌دهد و فروش و پرداخت را یک‌جا نگه می‌دارد.
              </p>
              <div className="landing-fade landing-fade-cta mt-10 flex flex-wrap items-center gap-x-6 gap-y-3">
                <a
                  href={start}
                  className="inline-flex h-12 items-center justify-center rounded-full bg-accent px-8 text-sm text-onAccent hover:bg-warm"
                >
                  رایگان شروع کن
                </a>
                <a href="#capabilities" className="text-sm text-ink/85 transition-colors hover:text-ink">
                  دیدن همهٔ امکانات
                </a>
              </div>
              <ul className="landing-fade landing-fade-cta mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px] text-ink/55">
                <li className="flex items-center gap-2">
                  <span className="h-1 w-1 rounded-full bg-warm/80" />
                  اتصال از مسیر رسمی
                </li>
                <li className="flex items-center gap-2">
                  <span className="h-1 w-1 rounded-full bg-warm/80" />
                  بدون پسورد اینستاگرام
                </li>
                <li className="flex items-center gap-2">
                  <span className="h-1 w-1 rounded-full bg-warm/80" />
                  پلن رایگان برای شروع
                </li>
              </ul>
            </div>
            <div className="landing-mark-stage pointer-events-none" aria-hidden>
              <div className="landing-mark-orbit">
                <div className="landing-mark-halo" />
                <div className="landing-mark-core">
                  <div className="landing-mark-turn">
                    <div className="landing-mark-breathe">
                      <img src="/sozan-mark.png?v=copper-1" alt="" width={112} height={112} />
                      <span className="landing-mark-shine" />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="border-b border-line/40">
          <div className="mx-auto max-w-6xl px-5 py-14 sm:px-8 sm:py-20">
            <p className="landing-kicker mb-10 text-center font-medium text-warm">از چت تا ویترین</p>
            <div className="landing-demo-stage pointer-events-none" aria-hidden>
              <div className="relative w-full max-w-sm">
                <div className="landing-demo-halo absolute inset-0" />
                <div className="landing-demo-card relative p-5">
                  <div className="flex items-center gap-3 border-b border-line/40 pb-4">
                    <img src="/sozan-mark.png?v=copper-1" alt="" className="h-9 w-9" />
                    <div className="flex-1">
                      <p className="text-sm font-medium text-ink">سوزان</p>
                      <p className="text-xs text-ink/50">همین حالا در چت بساز</p>
                    </div>
                    <span className="sozan-breathe h-1.5 w-1.5 rounded-full bg-accent" />
                  </div>
                  <div className="flex flex-col gap-2.5 pt-4">
                    <p className="landing-bubble landing-bubble-user landing-demo-msg text-ink/90">
                      یه فروشگاه لباس بساز؛ تیره و مینیمال.
                    </p>
                    <p className="landing-bubble landing-bubble-sozan landing-demo-msg landing-demo-msg-2 text-ink/85">
                      رنگ و حسش را گرفتم. بسازم؟
                    </p>
                    <p className="landing-bubble landing-bubble-user landing-demo-msg landing-demo-msg-3 text-ink/90">
                      بساز
                    </p>
                  </div>
                </div>
                <div className="landing-demo-card landing-demo-build relative mt-4 w-[86%] p-4">
                  <div className="flex items-center gap-1.5 border-b border-line/40 pb-3">
                    <span className="h-1.5 w-1.5 rounded-full bg-ink/25" />
                    <span className="h-1.5 w-1.5 rounded-full bg-ink/25" />
                    <span className="h-1.5 w-1.5 rounded-full bg-ink/25" />
                    <span className="mx-auto rounded-full bg-ink/5 px-3 py-1 text-[10px] text-ink/45">shop.sozan-core.ir</span>
                  </div>
                  <div className="pt-3">
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-medium text-ink/85">فروشگاهت</p>
                      <p className="text-[10px] text-warm">ساخته شد</p>
                    </div>
                    <div className="mt-3 grid grid-cols-3 gap-2">
                      {[
                        { name: "پیراهن مردانه", price: "۸۹۰" },
                        { name: "کیف چرمی", price: "۱٬۲۵۰" },
                        { name: "کلاه بافت", price: "۳۲۰" },
                      ].map((item) => (
                        <div key={item.name} className="rounded-lg border border-line/40 bg-ink/5 p-1.5">
                          <div className="landing-tile h-9 rounded-md" />
                          <p className="mt-1.5 truncate text-[9px] text-ink/70">{item.name}</p>
                          <p className="text-[9px] text-warm">نمونه · {item.price} هزار</p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="border-y border-line/40 bg-paper/20">
          <div className="mx-auto grid max-w-6xl gap-px bg-line/40 sm:grid-cols-3">
            {[
              ["یک پنل", "فروشگاه، محتوا، پیام و فروش"],
              ["سه کانال", "اینستاگرام، تلگرام و واتساپ"],
              ["بدون کدنویسی", "همه‌چیز با گفتگو و چند انتخاب"],
            ].map(([title, body]) => (
              <div key={title} className="bg-canvas px-5 py-8 sm:px-8">
                <p className="landing-display text-xl text-warm">{title}</p>
                <p className="mt-2 text-sm leading-7 text-ink/65">{body}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="capabilities" className="mx-auto max-w-6xl scroll-mt-20 px-5 py-16 sm:px-8 sm:py-24">
          <div className="max-w-3xl">
            <p className="landing-kicker font-medium text-warm">همهٔ چرخهٔ فروش</p>
            <h2 className="landing-display mt-3 text-[clamp(1.9rem,4vw,3.2rem)] leading-snug">
              فقط سایت‌ساز نیست؛ همکار روزانهٔ فروشگاهت است.
            </h2>
            <p className="landing-lede mt-5 text-base leading-8">
              از آوردن کالای واقعی تا ساخت ویترین، جذب مشتری، پاسخ‌گویی، گرفتن پول و کنترل موجودی؛ هر بخش به بخش بعدی وصل است.
            </p>
          </div>
          <div className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {CAPABILITIES.map((item) => (
              <article key={item.n} className="landing-feature-card flex min-h-72 flex-col rounded-3xl border border-line/50 bg-paper/35 p-6">
                <p className="landing-display text-sm text-accent/80">{item.n}</p>
                <h3 className="landing-display mt-5 text-xl leading-8">{item.title}</h3>
                <p className="landing-lede mt-3 text-sm leading-7">{item.body}</p>
                <ul className="mt-auto flex flex-wrap gap-2 pt-6">
                  {item.tags.map((tag) => (
                    <li key={tag} className="rounded-full border border-line/50 bg-canvas/60 px-3 py-1 text-[11px] text-ink/65">
                      {tag}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>

        <section id="how" className="scroll-mt-20 border-t border-line/40">
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24">
          <p className="landing-kicker font-medium text-warm">محصول را ببین</p>
          <h2 className="landing-display mt-3 max-w-3xl text-[clamp(1.9rem,4vw,3.2rem)] leading-snug">
            سه گفتگوی اصلی؛ از ایده تا فروش.
          </h2>
          <div className="mt-10 space-y-16 sm:space-y-24">
            {CHAPTERS.map((item, i) => (
              <article key={item.id} id={item.id} className="grid items-center gap-10 border-t border-line/40 pt-8 lg:grid-cols-[1.05fr_0.95fr] lg:gap-16">
                <div className={i % 2 === 1 ? "lg:order-2" : ""}>
                  <p className="landing-kicker font-medium text-warm">
                    <span className="landing-display me-3 text-base text-accent/80">{item.n}</span>
                    {item.kicker}
                  </p>
                  <h2 className="landing-display mt-3 text-[clamp(1.8rem,4vw,3.1rem)] leading-snug">
                    {item.title}
                  </h2>
                  <p className="landing-lede mt-5 text-base leading-8">{item.body}</p>
                </div>
                <div className={`max-w-sm ${i % 2 === 1 ? "lg:order-1" : ""}`} aria-hidden>
                  <ChapterVisual id={item.id} />
                </div>
              </article>
            ))}
          </div>
          </div>
        </section>

        <section className="border-y border-line/40 bg-paper/25">
          <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-6 px-5 py-10 sm:flex-row sm:items-center sm:px-8">
            <div>
              <p className="landing-display text-[clamp(1.4rem,2.8vw,2rem)]">کسب‌وکارت را به سوزان معرفی کن.</p>
              <p className="landing-lede mt-2 text-sm">از پلن رایگان شروع کن؛ اولین فروشگاهت را در چت بساز.</p>
            </div>
            <a
              href={start}
              className="inline-flex h-12 items-center justify-center rounded-full bg-accent px-8 text-sm text-onAccent hover:bg-warm"
            >
              ساخت حساب رایگان
            </a>
          </div>
        </section>

        <section className="border-y border-line/40 bg-paper/25">
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-20">
            <p className="landing-kicker font-medium text-warm">شروع ساده</p>
            <h2 className="landing-display mt-3 text-[clamp(1.8rem,4vw,2.8rem)]">از ویترین فعلی تا پنل یکپارچه، سه قدم</h2>
            <ol className="mt-10 grid gap-10 sm:grid-cols-3">
              {STEPS.map((step) => (
                <li key={step.n} className="border-t border-line/50 pt-6">
                  <p className="landing-display text-2xl text-accent/80">{step.n}</p>
                  <h3 className="mt-3 text-lg">{step.title}</h3>
                  <p className="landing-lede mt-3 text-sm leading-7">{step.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="channels" className="scroll-mt-20 border-b border-line/40">
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24">
            <div className="grid gap-10 lg:grid-cols-[0.8fr_1.2fr] lg:gap-16">
              <div>
                <p className="landing-kicker font-medium text-warm">کانال‌ها</p>
                <h2 className="landing-display mt-3 text-[clamp(1.9rem,4vw,3.1rem)] leading-snug">
                  مشتری هرجا هست، کار تو یک‌جا می‌ماند.
                </h2>
                <p className="landing-lede mt-5 text-base leading-8">
                  هر کانال توانایی متفاوتی دارد. سوزان دقیق نشان می‌دهد کدام حساب برای خواندن ویترین، انتشار محتوا یا دریافت پیام وصل شده است.
                </p>
              </div>
              <div className="divide-y divide-line/50 border-y border-line/50">
                {CHANNELS.map((channel) => (
                  <article key={channel.name} className="grid gap-3 py-6 sm:grid-cols-[10rem_1fr]">
                    <div>
                      <h3 className="landing-display text-lg">{channel.name}</h3>
                      <p className="mt-1 text-xs text-warm">{channel.lead}</p>
                    </div>
                    <p className="landing-lede text-sm leading-7">{channel.body}</p>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section id="plans" className="scroll-mt-20 bg-paper/20">
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24">
            <div className="max-w-3xl">
              <p className="landing-kicker font-medium text-warm">پلن‌ها</p>
              <h2 className="landing-display mt-3 text-[clamp(1.9rem,4vw,3.1rem)] leading-snug">
                رایگان شروع کن؛ وقتی کارت بیشتر شد ارتقا بده.
              </h2>
              <p className="landing-lede mt-5 text-base leading-8">
                تفاوت پلن‌ها در تعداد فروشگاه و کانال، سهمیهٔ پیامک و میزان خودکار بودن پاسخ مشتری است.
              </p>
            </div>
            <div className="mt-12 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {plans.map((plan) => (
                <PlanCard key={plan.id} plan={plan} start={start} until={catalog?.discountUntilLabel || ""} />
              ))}
            </div>
            {plans.length === 0 ? (
              <p className="mt-6 text-sm text-ink/70">قیمت پلن‌ها الان در دسترس نیست.</p>
            ) : null}
            <p className="mt-6 text-xs leading-6 text-ink/55">
              مبلغ روی کارت همان مبلغ پرداخت است و دورهٔ اشتراک ماهانه است.
              {catalog?.discountUntilLabel ? ` تخفیف تا ${catalog.discountUntilLabel}.` : ""}
            </p>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24">
          <p className="landing-kicker font-medium text-warm">پرسش‌ها</p>
          <h2 className="landing-display mt-3 text-[clamp(1.8rem,4vw,2.8rem)]">قبل از شروع چه باید بدانی؟</h2>
          <div className="mt-10 grid gap-x-12 md:grid-cols-2">
            {FAQS.map((item) => (
              <details key={item.q} className="group border-t border-line/40 py-5">
                <summary className="cursor-pointer list-none text-base text-ink/85 transition-colors group-open:text-ink hover:text-ink">
                  {item.q}
                </summary>
                <p className="landing-lede mt-3 text-sm leading-7">{item.a}</p>
              </details>
            ))}
          </div>
        </section>

        <section className="border-t border-line/40">
          <div className="mx-auto flex max-w-6xl flex-col gap-8 px-5 py-20 sm:px-8 sm:py-28 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl">
              <p className="landing-kicker font-medium text-warm">بگو، بساز، بفروش</p>
              <h2 className="landing-display mt-3 text-[clamp(2rem,5vw,3.4rem)] leading-snug">فروشگاهت را از همین امروز یک‌جا اداره کن.</h2>
              <p className="landing-lede mt-5 text-base leading-8">فقط با شماره موبایل وارد شو. پلن رایگان برای ساخت اولین فروشگاه آماده است.</p>
            </div>
            <a
              href={start}
              className="inline-flex h-12 items-center justify-center rounded-full bg-accent px-8 text-sm text-onAccent hover:bg-warm"
            >
              رایگان شروع کن
            </a>
          </div>
        </section>
      </main>

      <footer className="border-t border-line/40">
        <div className="mx-auto grid max-w-6xl gap-8 px-5 py-10 sm:grid-cols-[1fr_auto_auto] sm:items-center sm:px-8">
          <div>
            <div className="flex items-center gap-3">
              <SozanMark className="h-8 w-8" glow={false} />
              <p className="text-sm font-medium text-warm">سوزان</p>
            </div>
            <p className="mt-3 max-w-sm text-xs leading-6 text-ink/50">فروشگاه، محتوا، گفتگو و پرداخت برای فروشندهٔ ایرانی.</p>
          </div>
          <nav className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-ink/65">
            <a href="#capabilities" className="hover:text-warm">امکانات</a>
            <a href="#channels" className="hover:text-warm">کانال‌ها</a>
            <a href="#plans" className="hover:text-warm">پلن‌ها</a>
            {LEGAL.map((item) => (
              <a key={item.href} href={item.href} className="hover:text-warm">{item.label}</a>
            ))}
            <a href={panelOrigin || "https://app.sozan-core.ir"} className="hover:text-warm">ورود به پنل</a>
          </nav>
          <div className="flex items-center gap-4">
            <div dangerouslySetInnerHTML={{ __html: ENAMAD_SEAL }} />
            <span className="text-[11px] leading-5 text-ink/45">دارای نماد<br />اعتماد الکترونیکی</span>
          </div>
        </div>
        <div className="border-t border-line/30">
          <p className="mx-auto max-w-6xl px-5 py-4 text-center text-[11px] leading-6 text-ink/55 sm:px-8">
            ساخته شده توسط شرکت گهر شبکه کارمانیا
          </p>
        </div>
      </footer>
    </div>
  );
}
