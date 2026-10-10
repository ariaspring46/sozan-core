import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { SELLER_GUIDES, sellerGuideBySlug } from "@/lib/seller-guides";

export function generateStaticParams() {
  return SELLER_GUIDES.map((item) => ({ slug: item.slug }));
}

export default async function MoreDocsArticlePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const guide = sellerGuideBySlug(slug);
  if (!guide) notFound();
  return (
    <AppShell
      header={
        <div>
          <p className="text-sm text-muted">
            <Link href="/more/docs" className="tap text-warm">
              اسناد آموزشی
            </Link>
          </p>
          <h1 className="text-lg font-bold">{guide.title}</h1>
        </div>
      }
    >
      <article className="h-full space-y-5 overflow-y-auto p-4 [&>*]:mx-auto [&>*]:max-w-3xl">
        {guide.sections.map((section, index) => (
          <section key={section.heading || String(index)} className="rounded-2xl border border-line/80 bg-surface p-4 shadow-card">
            {section.heading ? <h2 className="mb-2 font-bold">{section.heading}</h2> : null}
            <div className="space-y-3">
              {section.paragraphs.map((paragraph, line) => (
                <p key={line} className="wrap-any text-[15px] leading-8 text-ink">
                  {paragraph}
                </p>
              ))}
            </div>
          </section>
        ))}
      </article>
    </AppShell>
  );
}
