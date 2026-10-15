import Link from 'next/link'

const STEPS = [
  { href: '/connect', n: 1, title: 'Connect', text: 'Paste a Ring Developer Playground token or link a Ring account. Devices and history appear.' },
  { href: '/library', n: 2, title: 'Library', text: 'Browse your events, add footage, and mark a few clips as + or − for the thing you care about.' },
  { href: '/teach', n: 3, title: 'Teach', text: 'Watch the agent sketch rules and a solver fit their numbers. Answer the one question it asks.' },
  { href: '/rule', n: 4, title: 'Rule', text: 'Backtest on your history with a false-alarm guarantee, see why each match fired, then deploy.' },
  { href: '/live', n: 5, title: 'Live', text: 'Deployed rules watch new events. Every alert comes with its explanation and its cost.' },
  { href: '/eval', n: 6, title: 'Eval', text: 'The same method on MEVA surveillance footage, against prompting a vision model per event.' },
]

export default function Home() {
  return (
    <div>
      <section className="rounded-2xl border border-ex-line bg-gradient-to-br from-ex-panel to-ex-bg px-6 py-10 sm:px-10">
        <p className="text-sm font-medium text-ex-accent">Ring developer hackathon 2026</p>
        <h1 className="mt-2 max-w-3xl text-4xl font-semibold tracking-tight text-ex-ink sm:text-5xl">
          Teach your Ring camera new detectors by example.
        </h1>
        <p className="mt-4 max-w-2xl text-lg text-ex-ink2">
          Ring understands four things: person, vehicle, package, other motion. Show Exemplar a clip or two of what you actually care about
          and it learns a readable rule, proves it on your history, and watches for it live.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link href="/connect" className="btn-primary">Get started</Link>
          <Link href="/eval" className="btn">See the evaluation</Link>
        </div>
      </section>

      <section aria-labelledby="steps-h" className="mt-8">
        <h2 id="steps-h" className="text-lg font-semibold text-ex-ink">How it works</h2>
        <ol className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map((s) => (
            <li key={s.href}>
              <Link href={s.href} className="block h-full rounded-xl border border-ex-line bg-ex-panel p-4 transition-colors hover:bg-ex-raised">
                <span className="flex items-center gap-3">
                  <span className="grid h-8 w-8 place-items-center rounded-full bg-ex-raised text-sm font-bold text-ex-accent" aria-hidden="true">{s.n}</span>
                  <span className="text-base font-semibold text-ex-ink">{s.title}</span>
                </span>
                <span className="mt-2 block text-sm text-ex-ink2">{s.text}</span>
              </Link>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="honest-h" className="mt-8 grid gap-4 md:grid-cols-3">
        <h2 id="honest-h" className="sr-only">What makes it different</h2>
        <div className="card"><p className="font-semibold text-ex-ink">Rules you can read</p><p className="mt-1 text-sm text-ex-ink2">Every rule is shown in plain English and in a small logic language. A solver, not a prompt, computes its thresholds.</p></div>
        <div className="card"><p className="font-semibold text-ex-ink">Proven before it goes live</p><p className="mt-1 text-sm text-ex-ink2">Backtests on your own history, with a false-alarm guarantee from randomly sampled labels, or an honest note that you don’t have one yet.</p></div>
        <div className="card"><p className="font-semibold text-ex-ink">Explained and cheap</p><p className="mt-1 text-sm text-ex-ink2">Each alert carries the facts and times that satisfied the rule. Clear matches and clear misses cost almost nothing.</p></div>
      </section>
    </div>
  )
}
