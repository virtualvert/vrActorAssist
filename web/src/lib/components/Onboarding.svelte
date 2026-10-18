<script lang="ts">
  import { ArrowLeft, ArrowRight } from "@lucide/svelte";
  import type { Role } from "../protocol";
  import { ROLE_INFO, ROLE_ORDER } from "../roles";
  import { app } from "../state.svelte";
  import Button from "./Button.svelte";
  import ConnectForm from "./ConnectForm.svelte";
  import Logo from "./Logo.svelte";
  import RoleCard from "./RoleCard.svelte";

  let picked = $state<Role | null>(null);
  let step = $state<"role" | "connect">("role");

  async function next() {
    if (!picked) return;
    app.onboarding = true;
    await app.call({ call: "setRole", args: { role: picked } });
    step = "connect";
  }

  function finish() {
    app.onboarding = false;
  }
</script>

<main class="onboarding">
  <div class="inner">
    <div class="hero">
      <Logo />
      <h1>Welcome to <span class="grad">vrcActorSync</span></h1>
      <p class="muted">Cues, sounds and cameras in sync for your VRChat production.</p>
    </div>

    {#if step === "role"}
      <section class="step">
        <h2>Which seat are you in?</h2>
        <p class="faint">The app will open in this role every time. You can change it later in Settings.</p>
        <div class="roles" role="radiogroup" aria-label="Role">
          {#each ROLE_ORDER as id (id)}
            <RoleCard info={ROLE_INFO[id]} selected={picked === id} onselect={() => (picked = id)} />
          {/each}
        </div>
        <div class="row end">
          <Button variant="primary" size="l" disabled={!picked} onclick={next}>
            Continue <ArrowRight size="1.2em" />
          </Button>
        </div>
      </section>
    {:else}
      <section class="step narrow card card-pad">
        <h2>Connect to your relay</h2>
        <p class="faint">You can skip this and connect later from Settings.</p>
        <ConnectForm submitLabel="Connect" ondone={finish} />
        <div class="row between">
          <Button variant="ghost" onclick={() => (step = "role")}><ArrowLeft size="1.1em" /> Back</Button>
          <Button variant="ghost" onclick={finish}>Skip for now</Button>
        </div>
      </section>
    {/if}
  </div>
</main>

<style>
  .onboarding {
    height: 100%;
    overflow-y: auto;
    display: grid;
    place-items: center;
    padding: 2rem 1rem;
  }

  .inner {
    width: min(64rem, 100%);
    display: flex;
    flex-direction: column;
    gap: 2.5rem;
    animation: rise-in 420ms var(--ease-out);
  }

  .hero {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 0.9rem;
  }

  .hero :global(.logo) {
    width: calc(var(--target) * 1.6);
    height: calc(var(--target) * 1.6);
  }

  h1 {
    font-size: clamp(1.8rem, 4vw, 2.75rem);
    font-weight: 800;
  }

  .grad {
    background: linear-gradient(120deg, var(--director), var(--actor) 50%, var(--camera));
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
  }

  .step {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .step h2 {
    font-size: 1.5rem;
  }

  .narrow {
    width: min(34rem, 100%);
    margin: 0 auto;
  }

  .roles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
    gap: 1rem;
    margin-top: 0.5rem;
  }

  .end {
    justify-content: flex-end;
  }

  .between {
    justify-content: space-between;
  }
</style>
