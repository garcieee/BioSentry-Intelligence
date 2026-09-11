import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import type { ClinicalNote, Measurement, PatientDetail as PatientDetailType, TierBFinding, TierCData } from "../types";
import { getPatient, getNotes, addNote, deleteNote } from "../api";
import { MeasurementDisplay } from "../components/MeasurementDisplay";
import { TrendChart } from "../components/TrendChart";
import { Sparkline } from "../components/Sparkline";
import styles from "./PatientDetail.module.css";

// --- Shared sub-components ---

function VitalRow<T>({
  label, measurement, unit,
}: {
  label: string; measurement: Measurement<T>; unit?: string;
}) {
  return (
    <div className={styles.vitalRow}>
      <span className={styles.vitalLabel}>{label}</span>
      <span className={styles.vitalValue}>
        <MeasurementDisplay measurement={measurement} unit={unit} />
      </span>
    </div>
  );
}

const DIRECTION_CHAR: Record<string, string> = {
  rising: "\u2191",
  falling: "\u2193",
  stable: "\u2192",
  new: "\u25C6",
};

// Tier B: a single mechanism finding row with its own value and units.
// Detail is always shown (density over minimalism).
function FindingRow({ finding }: { finding: TierBFinding }) {
  return (
    <div className={`${styles.findingRow} ${finding.significant ? styles.findingSignificant : ""}`}>
      <span className={styles.findingLabel}>{finding.label}</span>
      <span className={styles.findingValue}>
        {finding.value}
        {finding.direction && (
          <span className={styles.findingDirection}>
            {" "}{DIRECTION_CHAR[finding.direction] ?? ""}
          </span>
        )}
        <span className={styles.findingSource}>{finding.source}</span>
      </span>
      {finding.detail && (
        <span className={styles.findingDetail}>{finding.detail}</span>
      )}
    </div>
  );
}

const DEVICE_AXES = new Set(["af", "rr", "pi"]);
const LAB_SUBSTRATE = new Set(["trop", "k-mg", "kdigo", "lactate"]);
const SECONDARY_AXES = new Set(["hrv"]);

function fmtSignedContribution(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "\u2212" : "";
  return `${sign}${Math.abs(value).toFixed(2)}`;
}

// Reads the outcome model's own inference clock, not the vitals feed's.
function fmtScoredAgo(seconds: number): string {
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  const hours = Math.round(seconds / 3600);
  return `${hours} hour${hours === 1 ? "" : "s"} ago`;
}

// Tier C: calibrated outcome-model probability, its own freshness, and the
// signed feature attributions that make the score inspectable.
function TierCSection({ data }: { data: TierCData }) {
  const pct = Math.round(data.risk_probability * 100);
  const ranked = [...data.attributions]
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
    .slice(0, 6);
  const maxAbs = Math.max(...ranked.map((a) => Math.abs(a.contribution)), 1e-9);

  return (
    <div className={styles.tierC}>
      <div className={styles.riskHeadline}>
        <span className={styles.riskValue}>{pct}%</span>
        <span className={styles.riskCaption}>
          Deterioration risk &middot; {data.forecast_window}
        </span>
      </div>

      <p className={styles.modelFreshness}>
        Model last scored {fmtScoredAgo(data.scored_seconds_ago)}
      </p>

      <div className={styles.attrList}>
        {ranked.map((a) => {
          const half = (Math.abs(a.contribution) / maxAbs) * 50;
          const positive = a.contribution > 0;
          return (
            <div key={a.feature} className={styles.attrRow}>
              <span className={styles.attrLabel}>{a.feature}</span>
              <div className={styles.attrBar}>
                <span className={styles.attrZero} />
                <span
                  className={positive ? styles.attrBarPos : styles.attrBarNeg}
                  style={{ width: `${half}%` }}
                />
              </div>
              <span
                className={`${styles.attrVal} ${positive ? "" : styles.attrValNeg}`}
              >
                {fmtSignedContribution(a.contribution)}
              </span>
            </div>
          );
        })}
      </div>

      <p className={styles.tierCFooter}>Ranking signal only &mdash; not a diagnosis</p>
    </div>
  );
}

type Drawer = "notes" | "charts" | null;

// --- Main component ---

export function PatientDetail() {
  const { id } = useParams<{ id: string }>();
  const [patient, setPatient] = useState<PatientDetailType | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const [notes, setNotes] = useState<ClinicalNote[]>([]);
  const [noteText, setNoteText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [drawer, setDrawer] = useState<Drawer>(null);

  useEffect(() => {
    if (!id) return;
    getPatient(id).then((p) => {
      if (p) setPatient(p);
      else setNotFound(true);
    });
    getNotes(id).then(setNotes);
  }, [id]);

  const handleAddNote = async () => {
    if (!id || !noteText.trim() || submitting) return;
    setSubmitting(true);
    const note = await addNote(id, "RN Dela Cruz", "RN", noteText.trim());
    setNotes((prev) => [note, ...prev]);
    setNoteText("");
    setSubmitting(false);
  };

  const handleDeleteNote = async (noteId: string) => {
    if (!id) return;
    await deleteNote(id, noteId);
    setNotes((prev) => prev.filter((n) => n.id !== noteId));
  };

  const toggleDrawer = (d: Drawer) => setDrawer((prev) => prev === d ? null : d);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  if (notFound) {
    return (
      <main className={styles.page}>
        <p>Patient not found.</p>
        <Link to="/ward">Back to ward</Link>
      </main>
    );
  }

  if (!patient) return null;

  const reasons = patient.escalation_reasons;

  return (
    <div className={styles.page}>
      {/* Status strip */}
      <div className={styles.statusStrip}>
        <div className={styles.stripInner}>
          <Link to="/ward" className={styles.back}>&larr; Ward view</Link>
          <div className={styles.stripRight}>
            <span className={styles.stripSignal}>
              <span className={styles.liveDot} />
              Signal {patient.signal_quality}%
            </span>
            <span className={styles.stripUpdate}>
              {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
            <span className={styles.stripId}>{patient.id}</span>
          </div>
        </div>
      </div>

      {/* Summary bar: NEWS2 + escalation reasons (no rank, no tier badge) */}
      <div className={styles.summaryBar}>
        <div className={styles.summaryRow}>
          <div className={styles.summaryInner}>
            <div className={styles.summaryBlock}>
              <span className={styles.summaryLabel}>NEWS2</span>
              <span className={styles.summaryBig}>{patient.score}</span>
            </div>
            <div className={styles.summaryBlock}>
              <span className={styles.summaryLabel}>Signal</span>
              <span className={styles.summaryBig}>{patient.signal_quality}%</span>
            </div>
            <div className={styles.reasonBlock}>
              <span className={styles.summaryLabel}>Why this patient is up</span>
              {reasons.length > 0 ? (
                <div className={styles.reasonList}>
                  {reasons.map((r, i) => (
                    <span key={i} className={styles.reasonTag}>
                      {r.text}
                      {r.pathway && <span className={styles.reasonPathway}> ({r.pathway})</span>}
                    </span>
                  ))}
                </div>
              ) : (
                <span className={styles.reasonNone}>Sorted on NEWS2 only</span>
              )}
            </div>
          </div>
          <div className={styles.drawerButtons}>
            <button
              type="button"
              className={`${styles.drawerBtn} ${drawer === "notes" ? styles.drawerBtnActive : ""}`}
              onClick={() => toggleDrawer("notes")}
            >
              Notes{notes.length > 0 ? ` (${notes.length})` : ""}
            </button>
            <button
              type="button"
              className={`${styles.drawerBtn} ${drawer === "charts" ? styles.drawerBtnActive : ""}`}
              onClick={() => toggleDrawer("charts")}
            >
              Charts
            </button>
          </div>
        </div>
      </div>

      {/* Overlay panels */}
      {drawer && (
        <div className={styles.overlay}>
          <div className={styles.overlayBackdrop} onClick={() => setDrawer(null)} />
          <div className={styles.overlayPanel}>
            <div className={styles.overlayHeader}>
              <span className={styles.overlayTitle}>
                {drawer === "notes" ? `Clinical notes${notes.length > 0 ? ` \u00b7 ${notes.length}` : ""}` : "Vital trends -- last 6 hours"}
              </span>
              <button type="button" className={styles.overlayClose} onClick={() => setDrawer(null)}>&times;</button>
            </div>

            {drawer === "notes" && (
              <>
                <div className={styles.noteInput}>
                  <textarea
                    className={styles.noteTextarea}
                    placeholder="Add a clinical note..."
                    value={noteText}
                    onChange={(e) => setNoteText(e.target.value)}
                    rows={2}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleAddNote();
                    }}
                  />
                  <button
                    className={styles.noteSubmit}
                    onClick={handleAddNote}
                    disabled={!noteText.trim() || submitting}
                  >
                    Add note
                  </button>
                </div>
                {notes.length > 0 && (
                  <div className={styles.notesList}>
                    {notes.map((note) => (
                      <div key={note.id} className={styles.noteItem}>
                        <div className={styles.noteMeta}>
                          <span className={styles.noteAuthor}>{note.author}</span>
                          <span className={styles.noteRole}>{note.role}</span>
                          <span className={styles.noteTime}>
                            {new Date(note.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                          </span>
                          <button
                            type="button"
                            className={styles.noteDelete}
                            onClick={() => handleDeleteNote(note.id)}
                          >
                            Delete
                          </button>
                        </div>
                        <p className={styles.noteContent}>{note.content}</p>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            {drawer === "charts" && (
              <div className={styles.chartGrid}>
                <TrendChart
                  data={patient.vital_history.heart_rate}
                  label="Heart rate"
                  unit="bpm"
                  color="#e74c3c"
                  warningHigh={100}
                  warningLow={60}
                />
                <TrendChart
                  data={patient.vital_history.respiratory_rate}
                  label="Respiratory rate"
                  unit="/min"
                  color="#2980b9"
                  warningHigh={20}
                  warningLow={12}
                />
                <TrendChart
                  data={patient.vital_history.spo2}
                  label="SpO2"
                  unit="%"
                  color="#27ae60"
                  warningLow={94}
                />
              </div>
            )}
          </div>
        </div>
      )}

      <div className={styles.layout}>
        {/* Left: identity + tiers — all panels always open (density over progressive disclosure) */}
        <div className={styles.sidebar}>
          <div className={styles.panel}>
            <p className={styles.panelEyebrow}>Patient</p>
            <h1 className={styles.patientName}>{patient.name}</h1>
            <p className={styles.patientSub}>
              {patient.age ?? "--"} {patient.sex ?? "--"} &middot; Bed {patient.bed}
            </p>
            <p className={styles.admitting}>{patient.admitting_context}</p>
          </div>

          <div className={styles.panel}>
            <p className={styles.panelEyebrow}>Tier A &mdash; Reference score</p>
            <div className={styles.scoreBlock}>
              <span className={styles.scoreValue}>{patient.score}</span>
              <span className={styles.scoreLabel}>NEWS2</span>
            </div>
            <Sparkline
              data={patient.vital_trends.heart_rate}
              width={200}
              height={32}
              fill
            />
          </div>

          <div className={styles.panel}>
            <p className={styles.panelEyebrow}>Tier B &mdash; Mechanism findings</p>
            {patient.tier_b ? (
              <div className={styles.findingsGrid}>
                {(() => {
                  const findings = patient.tier_b.findings;
                  const device = findings.filter((f) => DEVICE_AXES.has(f.id));
                  const lab = findings.filter((f) => LAB_SUBSTRATE.has(f.id));
                  const secondary = findings.filter((f) => SECONDARY_AXES.has(f.id));
                  const other = findings.filter(
                    (f) => !DEVICE_AXES.has(f.id) && !LAB_SUBSTRATE.has(f.id) && !SECONDARY_AXES.has(f.id),
                  );
                  return (
                    <>
                      {device.length > 0 && (
                        <div className={styles.findingsGroup}>
                          <span className={styles.findingsGroupLabel}>Device axes</span>
                          {device.map((f) => <FindingRow key={f.id} finding={f} />)}
                        </div>
                      )}
                      {lab.length > 0 && (
                        <div className={styles.findingsGroup}>
                          <span className={styles.findingsGroupLabel}>Lab substrate</span>
                          {lab.map((f) => <FindingRow key={f.id} finding={f} />)}
                        </div>
                      )}
                      {secondary.length > 0 && (
                        <div className={styles.findingsGroup}>
                          <span className={styles.findingsGroupLabel}>Secondary</span>
                          {secondary.map((f) => <FindingRow key={f.id} finding={f} />)}
                        </div>
                      )}
                      {other.length > 0 && other.map((f) => <FindingRow key={f.id} finding={f} />)}
                    </>
                  );
                })()}
              </div>
            ) : (
              <p className={styles.pending}>not yet implemented</p>
            )}
          </div>

          <div className={styles.panel}>
            <p className={styles.panelEyebrow}>Tier C &mdash; Outcome model</p>
            {patient.tier_c ? (
              <TierCSection data={patient.tier_c} />
            ) : (
              <p className={styles.pending}>not yet implemented</p>
            )}
          </div>
        </div>

        {/* Right: vitals + labs (always visible) */}
        <div className={styles.main}>
          <div className={styles.panel}>
            <p className={styles.panelEyebrow}>Current vitals</p>
            <div className={styles.vitalsGrid}>
              <VitalRow label="Heart rate" measurement={patient.vitals.heart_rate} unit="bpm" />
              <VitalRow label="Respiratory rate" measurement={patient.vitals.respiratory_rate} unit="/min" />
              <VitalRow label="SpO2" measurement={patient.vitals.spo2} unit="%" />
              <VitalRow label="Temperature" measurement={patient.vitals.temperature} unit={"\u00b0C"} />
              <VitalRow label="Blood pressure" measurement={patient.vitals.blood_pressure} />
              <VitalRow label="Consciousness" measurement={patient.vitals.consciousness} />
            </div>
          </div>

          <div className={styles.panel}>
            <p className={styles.panelEyebrow}>
              Labs
              {patient.labs.freshness_hours !== null &&
                ` \u00b7 ${patient.labs.freshness_hours}h since collection`}
            </p>
            <div className={styles.vitalsGrid}>
              {patient.labs.troponin && <VitalRow label="Troponin" measurement={patient.labs.troponin} unit="ng/mL" />}
              {patient.labs.ck_mb && <VitalRow label="CK-MB" measurement={patient.labs.ck_mb} unit="U/L" />}
              {patient.labs.bnp && <VitalRow label="BNP" measurement={patient.labs.bnp} unit="pg/mL" />}
              {patient.labs.nt_probnp && <VitalRow label="NT-proBNP" measurement={patient.labs.nt_probnp} unit="pg/mL" />}
              {patient.labs.sodium && <VitalRow label="Sodium" measurement={patient.labs.sodium} unit="mEq/L" />}
              {patient.labs.potassium && <VitalRow label="Potassium" measurement={patient.labs.potassium} unit="mEq/L" />}
              {patient.labs.magnesium && <VitalRow label="Magnesium" measurement={patient.labs.magnesium} unit="mg/dL" />}
              {patient.labs.creatinine && <VitalRow label="Creatinine" measurement={patient.labs.creatinine} unit="mg/dL" />}
              {patient.labs.bun && <VitalRow label="BUN" measurement={patient.labs.bun} unit="mg/dL" />}
              {patient.labs.hemoglobin && <VitalRow label="Hemoglobin" measurement={patient.labs.hemoglobin} unit="g/L" />}
              {patient.labs.wbc && <VitalRow label="WBC" measurement={patient.labs.wbc} unit="x10^9/L" />}
              {patient.labs.platelet_count && <VitalRow label="Platelets" measurement={patient.labs.platelet_count} unit="/mm^3" />}
              {patient.labs.lactate && <VitalRow label="Lactate" measurement={patient.labs.lactate} unit="mmol/L" />}
              {patient.labs.sgpt && <VitalRow label="SGPT" measurement={patient.labs.sgpt} unit="U/L" />}
              {patient.labs.sgot && <VitalRow label="SGOT" measurement={patient.labs.sgot} unit="U/L" />}
              {patient.labs.blood_glucose && <VitalRow label="Blood glucose" measurement={patient.labs.blood_glucose} unit="mg/dL" />}
              {patient.labs.inr && <VitalRow label="INR" measurement={patient.labs.inr} unit="" />}
              {!patient.labs.troponin && !patient.labs.bnp && !patient.labs.potassium &&
               !patient.labs.creatinine && !patient.labs.hemoglobin && (
                <p className={styles.pending}>No lab values recorded</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
