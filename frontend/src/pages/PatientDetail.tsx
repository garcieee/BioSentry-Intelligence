import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import type { ClinicalNote, Measurement, PatientDetail as PatientDetailType } from "../types";
import { getPatient, getNotes, addNote, deleteNote } from "../api";
import { MeasurementDisplay } from "../components/MeasurementDisplay";
import { TrendChart } from "../components/TrendChart";
import { Sparkline } from "../components/Sparkline";
import styles from "./PatientDetail.module.css";

// --- Shared sub-components ---

function VitalRow<T>({
  label, measurement, unit, source,
}: {
  label: string; measurement: Measurement<T>; unit?: string; source?: string;
}) {
  return (
    <div className={styles.vitalRow}>
      <span className={styles.vitalLabel}>{label}</span>
      <span className={styles.vitalValue}>
        <MeasurementDisplay measurement={measurement} unit={unit} />
      </span>
      <span className={styles.vitalSource}>
        {source ?? measurement.provenance.source}
      </span>
    </div>
  );
}

function CollapsiblePanel({
  title,
  badge,
  defaultOpen = true,
  children,
}: {
  title: string;
  badge?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={styles.panel}>
      <button
        className={styles.panelToggle}
        onClick={() => setOpen((o) => !o)}
        type="button"
      >
        <span className={styles.panelEyebrow} style={{ marginBottom: 0 }}>
          {title}
          {badge && ` \u00b7 ${badge}`}
        </span>
        <span className={styles.toggleIcon}>{open ? "\u25B4" : "\u25BE"}</span>
      </button>
      {open && <div className={styles.panelBody}>{children}</div>}
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

      {/* Summary bar with drawer toggles */}
      <div className={styles.summaryBar}>
        <div className={styles.summaryRow}>
          <div className={styles.summaryInner}>
            <div className={styles.summaryBlock}>
              <span className={styles.summaryLabel}>Rank</span>
              <span className={styles.summaryBig}>#{patient.rank}</span>
            </div>
            <div className={styles.summaryBlock}>
              <span className={styles.summaryLabel}>NEWS2</span>
              <span className={styles.summaryBig}>{patient.score}</span>
            </div>
            <div className={styles.summaryBlock}>
              <span className={styles.summaryLabel}>Tier</span>
              <span className={styles.summaryBig}>{patient.sort_tier}</span>
            </div>
            <div className={styles.summaryBlock}>
              <span className={styles.summaryLabel}>Signal</span>
              <span className={styles.summaryBig}>{patient.signal_quality}%</span>
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
        {/* Left: identity + tiers */}
        <div className={styles.sidebar}>
          <div className={styles.panel}>
            <p className={styles.panelEyebrow}>Patient</p>
            <h1 className={styles.patientName}>{patient.name}</h1>
            <p className={styles.patientSub}>
              {patient.age ?? "--"} {patient.sex ?? "--"} &middot; Bed {patient.bed}
            </p>
            <p className={styles.admitting}>{patient.admitting_context}</p>
          </div>

          <CollapsiblePanel title="Tier A -- Reference score" defaultOpen>
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
          </CollapsiblePanel>

          <CollapsiblePanel title="Tier B -- Mechanism axes" defaultOpen={false}>
            {patient.tier_b ? (
              <div className={styles.axisGrid}>
                <div className={styles.axisItem}>
                  <span className={styles.axisLabel}>Arrhythmia burden</span>
                  <div className={styles.axisBar}>
                    <div
                      className={styles.axisBarFill}
                      style={{ width: `${(patient.tier_b.arrhythmia_burden ?? 0) * 100}%` }}
                    />
                  </div>
                  <span className={styles.axisVal}>
                    {patient.tier_b.arrhythmia_burden !== null
                      ? `${Math.round(patient.tier_b.arrhythmia_burden * 100)}%`
                      : "--"}
                  </span>
                </div>
                <div className={styles.axisItem}>
                  <span className={styles.axisLabel}>Respiratory</span>
                  <span className={styles.axisText}>
                    {patient.tier_b.respiratory_trajectory ?? "--"}
                  </span>
                </div>
                <div className={styles.axisItem}>
                  <span className={styles.axisLabel}>Perfusion index</span>
                  <div className={styles.axisBar}>
                    <div
                      className={styles.axisBarFill}
                      style={{ width: `${(patient.tier_b.perfusion_index ?? 0) * 100}%` }}
                    />
                  </div>
                  <span className={styles.axisVal}>
                    {patient.tier_b.perfusion_index?.toFixed(2) ?? "--"}
                  </span>
                </div>
                <div className={styles.axisItem}>
                  <span className={styles.axisLabel}>Substrate</span>
                  <span className={styles.axisText}>
                    {patient.tier_b.substrate_risk ?? "--"}
                  </span>
                </div>
              </div>
            ) : (
              <p className={styles.pending}>not yet implemented</p>
            )}
          </CollapsiblePanel>

          <CollapsiblePanel title="Tier C -- Outcome model" defaultOpen={false}>
            <p className={styles.pending}>not yet implemented</p>
          </CollapsiblePanel>
        </div>

        {/* Right: vitals + labs (always visible, no toggles) */}
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
              {patient.labs.troponin && <VitalRow label="Troponin" measurement={patient.labs.troponin} unit="ng/mL" source="lab" />}
              {patient.labs.ck_mb && <VitalRow label="CK-MB" measurement={patient.labs.ck_mb} unit="U/L" source="lab" />}
              {patient.labs.bnp && <VitalRow label="BNP" measurement={patient.labs.bnp} unit="pg/mL" source="lab" />}
              {patient.labs.nt_probnp && <VitalRow label="NT-proBNP" measurement={patient.labs.nt_probnp} unit="pg/mL" source="lab" />}
              {patient.labs.sodium && <VitalRow label="Sodium" measurement={patient.labs.sodium} unit="mEq/L" source="lab" />}
              {patient.labs.potassium && <VitalRow label="Potassium" measurement={patient.labs.potassium} unit="mEq/L" source="lab" />}
              {patient.labs.creatinine && <VitalRow label="Creatinine" measurement={patient.labs.creatinine} unit="mg/dL" source="lab" />}
              {patient.labs.bun && <VitalRow label="BUN" measurement={patient.labs.bun} unit="mg/dL" source="lab" />}
              {patient.labs.hemoglobin && <VitalRow label="Hemoglobin" measurement={patient.labs.hemoglobin} unit="g/L" source="lab" />}
              {patient.labs.wbc && <VitalRow label="WBC" measurement={patient.labs.wbc} unit="x10^9/L" source="lab" />}
              {patient.labs.platelet_count && <VitalRow label="Platelets" measurement={patient.labs.platelet_count} unit="/mm^3" source="lab" />}
              {patient.labs.sgpt && <VitalRow label="SGPT" measurement={patient.labs.sgpt} unit="U/L" source="lab" />}
              {patient.labs.blood_glucose && <VitalRow label="Blood glucose" measurement={patient.labs.blood_glucose} unit="mg/dL" source="lab" />}
              {patient.labs.inr && <VitalRow label="INR" measurement={patient.labs.inr} unit="" source="lab" />}
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
