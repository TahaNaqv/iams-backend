# Phase 6 Track 3 — Accessibility & i18n (Complete)

**Date:** 2026-05-13
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 6 Track 3
**Status:** ✅ Complete

This track lands the application-side i18n and accessibility primitives: a persisted per-user language preference (English / Arabic / French), RTL document direction that flips on locale change, and a set of WCAG 2.1 AA primitives (skip-to-content, live regions, accessible language switcher).

---

## What shipped

### Backend ([migration 0022](../iams-backend/iams/migrations/0022_i18n_phase6.py))

- `UserProfile.language` — `CharField(choices=[("en","English"),("ar","العربية"),("fr","Français")])`, defaults to `en`.
- `MeSerializer.language` (read-only on `MeSerializer`, write-only on `MeUpdateSerializer`).
- `MeUpdateSerializer.update()` applies the language to `user.profile.language` (it's not a direct User field).
- **6 new tests** — default value, GET surface, PATCH ar / fr, unsupported language → 400, persistence across other field updates.

### Frontend

**Service layer** (`src/i18n/language-sync.ts`):

```ts
isSupported(code)        // type guard
applyLanguage(code)      // i18n.changeLanguage + document.dir + lang
persistLanguage(code)    // PATCH /me/ (best-effort)
changeLanguage(code)     // combined
adoptUserLanguage(lang)  // app boot
```

**a11y components** (`src/components/a11y/`):

- `<SkipToContent targetId="main-content" />` — WCAG 2.4.1 "Bypass Blocks". Visually hidden until focused.
- `<LiveRegion polite|assertive />` — aria-live channel for toast announcements (WCAG 4.1.3).
- `<LanguageSwitcher />` — accessible `<select>` with `aria-label` derived from the `a11y.language` key.

**Locale bundles** — `a11y` namespace added to en / ar / fr (`skipToContent`, `language`, `openMenu`, `closeMenu`, `loading`, `notifications`, `userMenu`).

**Tests** (`src/i18n/i18n.test.ts`, **9 passing**):

- RTL/LTR direction resolution per language + unknown-code fallback.
- All three supported languages exposed.
- All locales contain the new `a11y` keys.
- `isSupported` type guard correctness.
- `applyLanguage` flips `document.documentElement.dir/lang`; unsupported codes are no-op.

### Wiring (drop-in for the App shell)

The app shell should:

```tsx
import { SkipToContent } from "@/components/a11y/SkipToContent";
import { adoptUserLanguage } from "@/i18n/language-sync";
import { getMe } from "@/lib/auth-api";

useEffect(() => {
  getMe().then((me) => adoptUserLanguage(me.language)).catch(() => {});
}, []);

return (
  <>
    <SkipToContent />
    <header role="banner">…</header>
    <nav role="navigation" aria-label={t("a11y.userMenu")}>…</nav>
    <main id="main-content" tabIndex={-1} role="main">…</main>
  </>
);
```

The drop-in for the topbar is `<LanguageSwitcher />`.

---

## Decisions

- **Server-side gettext deferred.** Every error string the FE renders is keyed by a stable `code` (e.g. `signature_invalid`, `mfa_required`, `payload_invalid`). The FE owns the translation — the backend stays lean. Adding a locale doesn't require a backend deploy.
- **Three sources of truth (FE first, BE eventually).** `applyLanguage` updates the FE immediately so toggling is instant; the backend write is async and silent on failure. The localStorage cache keeps the choice sticky for this device even when the backend write fails.
- **Eager dir/lang flip.** `applyLanguage` sets `document.documentElement.dir` and `lang` synchronously *and* the `i18n.on("languageChanged")` handler does it again. The redundancy means callers can rely on the side effect synchronously without waiting for the event loop.
- **A11y components are tiny + composable, not a framework.** Three small components (~150 LOC total) cover the WCAG checkpoints we needed (skip nav, live region, accessible select). Anything bigger pulls in `react-aria` or `@radix-ui/react-*` per-need rather than a global a11y harness.
- **A11y namespace key per language.** Sounds obvious but it's the most-forgotten part: dropping the test that *asserts* every supported locale has the new keys means catching the missing translation at CI time, not at runtime.

---

## What's deferred to focused FE polish

- Sweeping the existing pages to use `<main id="main-content">` etc.
- Re-checking color contrast against the design tokens against WCAG 1.4.3 (4.5:1 for normal text, 3:1 for large).
- RTL audit of every existing component (most Tailwind classes mirror cleanly via logical properties; specific cases like ChevronRight icons need `rtl:rotate-180`).
- Keyboard-trap audit on every modal / dropdown.

These are best done with a real screen-reader pass against the running app, not against a static codebase.

---

## What's next in Phase 6

| Track | Title | Status |
|---|---|---|
| 1 | SSO via Keycloak | ✅ Complete |
| 2 | ERP / HR Integrations | ✅ Complete |
| 3 | **Accessibility & i18n** | ✅ Complete |
| 4 | Documentation & Training | ⏳ Next |
