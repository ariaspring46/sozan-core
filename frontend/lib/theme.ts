export type ThemeChoice = "light" | "dark" | "system";

export const THEME_KEY = "sozan_theme";
export const THEME_BAR = { light: "#F4EFE8", dark: "#2F2F33" } as const;

/** اسکریپت پیش از رندر در <head>: تم ذخیره‌شده را بدون چشمک روی <html> می‌نشاند. */
export const THEME_BOOT = `(function(){try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t);var c=t==="light"?"${THEME_BAR.light}":"${THEME_BAR.dark}";document.querySelectorAll('meta[name="theme-color"]').forEach(function(m){m.setAttribute("content",c)})}}catch(e){}})();`;

export function readTheme(): ThemeChoice {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function systemTheme(): "light" | "dark" {
  try {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  const effective = choice === "system" ? systemTheme() : choice;
  document.querySelectorAll('meta[name="theme-color"]').forEach((meta) => {
    const media = meta.getAttribute("media");
    // در حالت «خودکار» متاهای media-دار خودشان درست‌اند؛ فقط انتخاب دستی همه را یکی می‌کند.
    if (choice === "system" && media) {
      meta.setAttribute("content", media.includes("light") ? THEME_BAR.light : THEME_BAR.dark);
    } else {
      meta.setAttribute("content", THEME_BAR[effective]);
    }
  });
}

export function saveTheme(choice: ThemeChoice) {
  try {
    if (choice === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, choice);
  } catch {
    /* ذخیره نشد؛ فقط برای همین بارگذاری اعمال می‌شود */
  }
  applyTheme(choice);
}
