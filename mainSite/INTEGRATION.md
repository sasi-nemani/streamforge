# StreamForge Product Page — Integration Guide

## File Structure

```
mainSite/
├── streamforge.html          ← Preview wrapper (local only)
├── assets/
│   ├── css/streamforge.css   ← All page styles (sf- namespaced)
│   └── js/streamforge.js     ← All page JS (IIFE, no globals)
└── INTEGRATION.md            ← This file
```

## How to integrate into loonlabs.io

### 1. Add the stylesheet to your site `<head>`

```html
<link rel="stylesheet" href="/streamforge/assets/css/streamforge.css" />
```

Or inline/import into your existing CSS bundle:
```css
@import '/streamforge/assets/css/streamforge.css';
```

### 2. Drop the page content into your template

Copy everything between the integration markers in `streamforge.html`:

```html
<!-- Drop this into your /streamforge page template -->
<div id="sf-page">
  <!-- ... all section content ... -->
</div>
```

Your site's existing `<nav>` and `<footer>` wrap it as usual.

### 3. Add the script before `</body>`

```html
<script src="/streamforge/assets/js/streamforge.js"></script>
```

### 4. Font dependency

The page uses Inter and JetBrains Mono. If your main site already loads
Inter, you can remove the Google Fonts link from the preview `<head>`.
JetBrains Mono is only used for code blocks — you can substitute any
monospace font by overriding:

```css
#sf-page { --sf-mono: 'Your Mono Font', monospace; }
```

## CSS Isolation

All rules are scoped inside `#sf-page { }` or use the `.sf-` prefix.
No global selectors (`body`, `h1`, `a`, etc.) are touched.
Safe to drop alongside any existing CSS without conflicts.

## Anchor links

Internal anchor links use `#sf-hero`, `#sf-problem`, `#sf-how-it-works`, etc.
These won't conflict with your site's own anchor IDs.

## Local preview

Open `streamforge.html` directly in a browser. The preview wrapper
provides the dark body background and font imports. Strip it when integrating.
