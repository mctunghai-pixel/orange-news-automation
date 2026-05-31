/**
 * Orange News — Telegram subscribe section (footer-д оруулна)
 * =============================================================
 * Хэрэглэх:
 *   1. Энэ файлыг website repo руу хуулна (жишээ нь src/components/TelegramFooter.tsx)
 *   2. assets/telegram_qr.png-г website-ийн public/ folder-д хуул:
 *        cp "Orange News-Automation/assets/telegram_qr.png" <website-repo>/public/
 *   3. Footer component-д import & render:
 *        import TelegramFooter from "@/components/TelegramFooter"
 *        ...
 *        <TelegramFooter />
 *
 * Tailwind-тэй ажиллана (utility classes ашигласан). Custom CSS шаардлагагүй.
 */
import Image from "next/image"

export default function TelegramFooter() {
  return (
    <section
      aria-labelledby="telegram-subscribe-heading"
      className="border-t border-zinc-200 bg-gradient-to-br from-orange-50 via-white to-orange-50 py-12 dark:border-zinc-800 dark:from-zinc-900 dark:via-zinc-950 dark:to-zinc-900"
    >
      <div className="mx-auto flex max-w-6xl flex-col items-center gap-8 px-6 md:flex-row md:items-center md:justify-between">
        {/* Зүүн тал — текст + CTA */}
        <div className="flex-1 text-center md:text-left">
          <span className="inline-flex items-center rounded-full bg-orange-100 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-orange-700 dark:bg-orange-900/40 dark:text-orange-300">
            📨 Telegram channel
          </span>

          <h2
            id="telegram-subscribe-heading"
            className="mt-4 text-2xl font-bold text-zinc-900 md:text-3xl dark:text-zinc-100"
          >
            Дэлхийн мэдээг цаг тутамд Telegram-аар
          </h2>

          <p className="mt-3 text-base text-zinc-600 md:max-w-md dark:text-zinc-400">
            Bloomberg, Reuters, WSJ, CNBC эх сурвалжуудын онцлох мэдээг Монгол
            хэлээр, өдөрт 10 удаа. QR код-оор скан хийгээд нэгдээрэй.
          </p>

          <div className="mt-6 flex flex-col items-center gap-3 md:flex-row md:items-start">
            <a
              href="https://t.me/OrangeNewsMN"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-lg bg-[#229ED9] px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-[#1e8bc0] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#229ED9]"
            >
              <svg
                className="h-5 w-5"
                viewBox="0 0 24 24"
                fill="currentColor"
                aria-hidden="true"
              >
                <path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71L12.6 16.3l-1.99 1.93c-.23.23-.42.42-.83.42z" />
              </svg>
              t.me/OrangeNewsMN
            </a>

            <a
              href="https://t.me/OrangeNewsMN"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-zinc-500 underline-offset-4 hover:underline dark:text-zinc-400"
            >
              эсвэл шууд нэгдэх →
            </a>
          </div>
        </div>

        {/* Баруун тал — QR код */}
        <div className="flex flex-col items-center gap-3">
          <div className="rounded-2xl bg-white p-4 shadow-lg ring-1 ring-zinc-200 dark:ring-zinc-700">
            <Image
              src="/telegram_qr.png"
              alt="Orange News Telegram channel QR code — t.me/OrangeNewsMN"
              width={180}
              height={180}
              className="h-[180px] w-[180px]"
              priority={false}
            />
          </div>
          <p className="text-xs font-medium uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
            Сканнаар нэгдэх
          </p>
        </div>
      </div>
    </section>
  )
}
