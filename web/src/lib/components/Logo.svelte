<script lang="ts">
  // Static mark: relay in the middle, director / actor / camera around it.
</script>

<svg class="logo" viewBox="0 0 64 64" aria-hidden="true">
  <defs>
    <linearGradient id="logo-g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="var(--accent)" />
      <stop offset="1" stop-color="var(--accent-2)" />
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="18" fill="var(--surface-3)" stroke="var(--border-strong)" />
  <path d="M19 23 L28 30 M45 23 L36 30 M32 40 L32 47" stroke="url(#logo-g)" stroke-width="3.5" stroke-linecap="round" />
  <circle cx="32" cy="33" r="7.5" fill="url(#logo-g)" />
  <circle cx="16" cy="20" r="5.5" fill="var(--director)" />
  <circle cx="48" cy="20" r="5.5" fill="var(--actor)" />
  <circle cx="32" cy="51" r="5.5" fill="var(--camera)" />
</svg>

<style>
  .logo {
    width: calc(var(--target) * 0.95);
    height: calc(var(--target) * 0.95);
    flex: none;
  }
</style>
