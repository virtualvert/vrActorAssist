<script lang="ts">
  // Static mark: the call (head) goes out to director / actor / camera (bark lines).
  // Same shapes as assets/icon-small.svg, in theme colours; scripts/gen_icons.py makes the app icon.
</script>

<svg class="logo" viewBox="0 0 64 64" aria-hidden="true">
  <defs>
    <linearGradient id="logo-g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="var(--accent)" />
      <stop offset="1" stop-color="var(--accent-2)" />
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="18" fill="var(--surface-3)" stroke="var(--border-strong)" />
  <path d="M45.29 9.32c-1.85 2.21-4.87 6.02-6.58 8.3l-1.66 2.23l-2.93 0.4c-1.59 0.23-3.1 0.46-3.35 0.52c-0.24 0.06-0.89 0.22-1.45 0.36l-1.02 0.26l-1.98 1.91l-1.99 1.91l-0.87 0c-0.47 0-2.48-0.04-4.45-0.09c-2.99-0.07-6.93 0-7.09 0.14c-0.01 0.01-0.09 0.44-0.17 0.95l-0.15 0.94l0.49 1.04c0.28 0.58 0.68 1.61 0.91 2.3l0.41 1.24l1.93 0.8c1.77 0.74 10.94 4.63 11.61 4.92l0.28 0.14l-0.28 0.17c-1.02 0.64-11.19 7.43-11.22 7.5c-0.03 0.05 0.23 0.8 0.58 1.69l0.64 1.61l0.26 0c0.55 0 3.37-0.5 4.15-0.74c2.03-0.6 5.01-1.39 5.26-1.39c0.46 0 4.05 1.7 5.28 2.52c0.74 0.48 1.72 1.36 2.71 2.42c2.21 2.39 4.08 3.81 5.74 4.38l0.82 0.29l0.39-0.42c0.2-0.23 0.96-1.09 1.66-1.88c1.18-1.33 6.5-6.68 12.13-12.18l2.26-2.21l-1.16-1.62c-0.63-0.89-1.97-2.77-2.98-4.18c-3.88-5.41-5.46-7.67-5.46-7.8c0-0.07 0.28-0.92 0.62-1.87l0.62-1.75l-0.43-2.06c-0.23-1.13-0.6-2.91-0.8-3.95c-0.61-3.01-1.66-7.97-1.68-8c-0.01-0.01-0.49 0.53-1.05 1.2z" fill="url(#logo-g)" />
  <path d="M6.15 31.4 L12.38 33.87" stroke="var(--director)" stroke-width="4.2" />
  <path d="M5.5 38.34 L13.07 37.84" stroke="var(--actor)" stroke-width="4.2" />
  <path d="M7.19 44.94 L13.61 41.52" stroke="var(--camera)" stroke-width="4.2" />
</svg>

<style>
  .logo {
    width: calc(var(--target) * 0.95);
    height: calc(var(--target) * 0.95);
    flex: none;
  }
</style>
