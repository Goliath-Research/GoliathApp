# Goliath Research org hub — wireframe & DNS cutover

**Status:** Draft (2026-09-22)  
**Repo:** `Goliath-Research/GoliathApp` (org/platform docs home until a dedicated website repo exists)  
**Related:** [`SEPARATION_PLAN.md`](./SEPARATION_PLAN.md)

## Intent

Three surfaces, not one:

| Surface | Job | Stack |
|---------|-----|--------|
| **Org hub** (`www.goliathresearch.com`) | Mission, platforms story, open source, partner contact | New site Goliath Research controls |
| **Academy** (`academy.goliathresearch.com`) | Courses, enroll, certificates | **LearnWorlds** (keep; do not reimplement) |
| **GoliathOmics portal** (`omics.goliathresearch.com` or similar) | Login, studies, workers, runs | Middle-tier / portal once migrated |

The hub **never** reimplements the LMS or the app — it only **links and explains**.

---

## Nav (sticky)

**Left:** Goliath Research  

**Center:** Learn · Platforms · Open source · About · Contact  

**Right buttons:**

- **Academy** → `https://academy.goliathresearch.com`
- **GoliathOmics** → `https://omics.goliathresearch.com` (until live: hub “Coming soon” or disabled button)

Footer repeats both buttons + GitHub org (`Goliath-Research`) + contact email.

---

## Homepage copy (draft)

### Hero

**Teach computational science. Share open platforms.**

Goliath Research Inc is a non-profit-oriented organization that teaches data science online and publishes open software so labs and learners can run real workflows — from a generic application platform to genomics.

**[Go to Academy]** **[Open GoliathOmics]**  

Secondary link: View our open-source projects →

### Three doors

**Learn**  
Self-paced courses with e-books and Jupyter notebooks — not video lectures. Hosted on our LearnWorlds academy.  
→ Start learning

**Build**  
**GoliathApp** — Meta model, RBAC, portal UI, workflow engine, REST middle-tier, and remote workers. One platform, many applications.  
→ Platform overview

**Specialize**  
**GoliathOmics** — methylation and liquid-biopsy workflows (open MIT components), with tools such as mojo-align and MethylExtractor, and an optional NVIDIA Clara Parabricks path.  
→ Omics overview · Open portal

### How the pieces connect

Academy (LearnWorlds) teaches the foundations.  
GoliathApp is the reusable engine.  
GoliathOmics is the genomics product and portal.  
mojo-align and MethylExtractor are utilities the portal’s workers can call.

*(Diagram: Learn → GoliathApp → GoliathOmics → Tools)*

### Open source

Cards with links: GoliathApp · GoliathOmics · mojo-align · MethylExtractor  

Status chips: Live / In progress / Planned (match reality — App extraction in progress, Omics migrating, tools public).

### Collaborate

Academic cores and partners can smoke-test on **their** HPC or cloud. We share code and docs; we do not ask you to ship samples offsite for marketing demos.  
→ Contact for a technical discussion

### Closing band

Same two CTAs: **Academy** · **GoliathOmics**

---

## Inner pages (one screen each)

| Page | Primary button | Label |
|------|----------------|--------|
| `/learn` | Academy URL | **Enter Academy** |
| `/platforms/goliath-app` | GitHub GoliathApp (+ docs later) | **View on GitHub** |
| `/platforms/goliath-omics` | Portal URL when ready | **Open GoliathOmics portal** |
| `/platforms/tools` | Sibling repos | **mojo-align** / **MethylExtractor** |
| `/open-source` | `github.com/Goliath-Research` | **Browse the organization** |
| `/about` | Contact | **Contact us** |

**Omics page until portal migrates:**  
**Open GoliathOmics portal** → disabled or “Notify me”, plus **View public repos** as the live action.

---

## Button label cheat sheet

Use these labels everywhere for consistency:

- **Go to Academy**
- **Open GoliathOmics**
- **View on GitHub**
- **Contact us**

---

## DNS / cutover checklist

**Goal:** `www` = hub only · `academy` = LearnWorlds · `omics` = portal (later)

### 1. Inventory today

- [ ] What do apex `goliathresearch.com` and `www` point at now (LearnWorlds vs other)?
- [ ] Confirm LearnWorlds custom domain is (or will be) `academy.goliathresearch.com`.

### 2. Before cutover

- [ ] Hub site built and previewable (e.g. Cloudflare Pages / Vercel staging URL).
- [ ] LearnWorlds custom domain verified on `academy`.
- [ ] Hub links use absolute Academy URL (not relative paths into the LMS).
- [ ] Omics portal hostname chosen (`omics.` recommended); TLS ready when the app moves.

### 3. Cutover (low-traffic window)

- [ ] Point `academy` CNAME to LearnWorlds (per their DNS docs).
- [ ] Point `www` (and ideally apex → www) to the **hub** host.
- [ ] Leave Omics DNS unset or parked on hub “coming soon” until migration day.
- [ ] Update LearnWorlds site URL / transactional emails so login links use `academy`, not `www`.

### 4. After cutover

- [ ] `www` → hub homepage with Academy + Omics buttons.
- [ ] `academy` → LMS login/catalog.
- [ ] Old `www` course deep links: 301 to matching Academy URLs if LearnWorlds provides them; else soft redirect with an Academy banner.
- [ ] Verify academy subdomain health from outside.
- [ ] Search Console / sitemap for hub only; do not duplicate LMS pages on `www`.

### 5. Omics migration day (later)

- [ ] `omics` → middle-tier / portal load balancer.
- [ ] Flip hub button from “Coming soon” to **Open GoliathOmics portal**.
- [ ] CORS / cookies: portal on `omics.`, hub on `www` — separate sessions unless SSO is added later.

---

## Out of scope for this doc

- Implementing the static hub site (separate repo or Pages project).
- Changing LearnWorlds course content.
- Migrating the GoliathOmics portal hostname (tracked with the App/Omics separation work).

---

*End of draft.*
