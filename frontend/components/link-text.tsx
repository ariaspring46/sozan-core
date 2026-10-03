import { Fragment } from "react";

const URL_RE = /(https?:\/\/[^\s،؛)»]+)/g;

/**
 * متن فارسی با نشانی داخلش: نشانی جهت چپ‌به‌راست و جدای خودش را دارد (وگرنه «https://a-b.ir» وسط جمله خرد می‌شود)
 * و قابل لمس است. نشانی هرگز وسط خط و روی خط‌تیره بریده نمی‌شود.
 */
export function LinkText({ text }: { text: string }) {
  const parts = String(text || "").split(URL_RE);
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <a
            key={index}
            href={part}
            target="_blank"
            rel="noreferrer"
            dir="ltr"
            className="inline-block max-w-full break-all align-bottom text-warm underline [unicode-bidi:isolate]"
          >
            {part.replace(/^https?:\/\//, "")}
          </a>
        ) : (
          <Fragment key={index}>{part}</Fragment>
        ),
      )}
    </>
  );
}
