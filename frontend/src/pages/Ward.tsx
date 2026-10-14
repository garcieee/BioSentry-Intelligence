import { useCallback, useEffect, useState } from "react";
import type { AbstainedRow as AbstainedRowType, Session, VitalsRecorded, WardResponse } from "../types";
import { canRecordVitals, getWard } from "../api";
import { WardRow } from "../components/WardRow";
import { AbstainedRow } from "../components/AbstainedRow";
import { SessionMenu } from "../components/SessionMenu";
import { standing } from "../components/vitalsDraft";
import styles from "./Ward.module.css";

interface Props {
  session: Session;
  onSignOut: () => void;
}

export function Ward({ session, onSignOut }: Props) {
  const [data, setData] = useState<WardResponse | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    getWard().then(setData);
  }, []);

  // A recorded value changes a patient's standing, which only the server can compute: say
  // what it said, then fetch the ward again so the ranking on screen is the server's.
  const handleRecorded = useCallback((row: AbstainedRowType, recorded: VitalsRecorded) => {
    setNotice(`Recorded for ${row.name}. ${standing(recorded)}`);
    getWard()
      .then(setData)
      .catch(() => setNotice("Recorded, but the ward could not be refreshed. Reload to see the ranking."));
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  if (!data) return null;

  const liveTiers = data.tier_status.filter((t) => t.live);
  const pendingTiers = data.tier_status.filter((t) => !t.live);

  return (
    <div className={styles.page}>
      {/* Status bar */}
      <div className={styles.statusBar}>
        <div className={styles.statusInner}>
          <div className={styles.statusLeft}>
            <span className={styles.statusItem}>
              <span className={styles.statusLabel}>BioSentry</span>
              <span className={styles.statusValue}>Ward {data.ward}</span>
            </span>
            <span className={styles.statusDivider} />
            <span className={styles.statusItem}>
              <span className={`${styles.liveDot} ${data.receiving_data ? styles.liveDotActive : ""}`} />
              <span className={styles.statusValue}>
                {data.receiving_data
                  ? now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
                  : "No signal"}
              </span>
            </span>
          </div>
          <div className={styles.statusRight}>
            <SessionMenu session={session} onSignOut={onSignOut} />
          </div>
        </div>
      </div>

      {/* Summary cards */}
      <div className={styles.summary}>
        <div className={styles.summaryInner}>
          <div className={styles.summaryCard}>
            <span className={styles.summaryNumber}>{data.ranked.length}</span>
            <span className={styles.summaryLabel}>Ranked</span>
          </div>
          <div className={styles.summaryCard}>
            <span className={styles.summaryNumber}>{data.abstained.length}</span>
            <span className={styles.summaryLabel}>Not ranked</span>
          </div>
          <div className={styles.summaryCard}>
            <span className={styles.summaryNumber}>
              {data.ranked.filter((r) => r.trend === "rising").length}
            </span>
            <span className={styles.summaryLabel}>Rising</span>
          </div>
          <div className={styles.summaryCard}>
            <span className={styles.summaryNumber}>
              {liveTiers.map((t) => t.label).join(", ") || "None"}
            </span>
            <span className={styles.summaryLabel}>Active tiers</span>
          </div>
          <div className={styles.summaryCard}>
            <span className={styles.summaryNumber}>
              {pendingTiers.length > 0
                ? pendingTiers.map((t) => t.tier).join(", ")
                : "None"}
            </span>
            <span className={styles.summaryLabel}>Pending</span>
          </div>
        </div>
      </div>

      {/* Main content */}
      <main className={styles.container}>
        <div className={styles.sectionHeader}>
          <p className={styles.eyebrow}>Priority queue</p>
          <p className={styles.sortInfo}>
            Sorted on Tier {data.sort_tier}
          </p>
        </div>

        {notice !== null && (
          <p className={styles.notice} role="status">
            {notice}{" "}
            <button type="button" className={styles.noticeClose} onClick={() => setNotice(null)}>
              Dismiss
            </button>
          </p>
        )}

        <div className={styles.rowList}>
          {data.ranked.map((row) => (
            <WardRow key={row.id} row={row} />
          ))}
        </div>

        {data.abstained.length > 0 && (
          <>
            <div className={styles.sectionHeader}>
              <p className={styles.eyebrow}>
                Not ranked ({data.abstained.length})
              </p>
              <p className={styles.sortInfo}>
                Action required to enable scoring
              </p>
            </div>
            <div className={styles.rowList}>
              {data.abstained.map((row) => (
                <AbstainedRow
                  key={row.id}
                  row={row}
                  canRecord={canRecordVitals}
                  clinicianId={session.clinician_id}
                  onRecorded={handleRecorded}
                />
              ))}
            </div>
          </>
        )}
      </main>

      <footer className={styles.footer}>
        Advisory only. BioSentry does not replace a monitor alarm. Every view is
        logged for audit under {session.clinician_id}.
      </footer>
    </div>
  );
}
