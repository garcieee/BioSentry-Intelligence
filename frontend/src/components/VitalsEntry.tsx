import { useState } from "react";
import { recordVitals } from "../api";
import { DIASTOLIC_BOUNDS, SYSTOLIC_BOUNDS } from "../api/bounds";
import type { VitalsRecorded } from "../types";
import {
  ACVPU_CHOICES,
  EMPTY_DRAFT,
  type DraftProblems,
  type VitalsDraft,
  echoDraft,
  standing,
  submitDraft,
} from "./vitalsDraft";
import styles from "./VitalsEntry.module.css";

// --- Presentation: everything the form shows is a function of its props ---

export interface VitalsEntryFormProps {
  readonly patientId: string;
  readonly patientName: string;
  readonly clinicianId: string;
  readonly draft: VitalsDraft;
  readonly problems: DraftProblems;
  readonly busy: boolean;
  readonly failure: string | null;
  readonly standingText: string | null;
  readonly onChange: (draft: VitalsDraft) => void;
  readonly onSubmit: () => void;
  readonly onClose: () => void;
}

export function VitalsEntryForm(props: VitalsEntryFormProps) {
  const { patientId, patientName, clinicianId, draft, problems, busy } = props;
  const { failure, standingText, onChange, onSubmit, onClose } = props;
  const echo = echoDraft(draft);
  const group = (name: string) => `${patientId}-${name}`;

  return (
    <form
      className={styles.form}
      aria-label={`Record vitals for ${patientName}`}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <p className={styles.title}>Record vitals</p>
      <p className={styles.sub}>
        Enter what you measured. A field left as &ldquo;Not recorded&rdquo; stays as it is; nothing
        is filled in for you.
      </p>

      <fieldset className={styles.group} disabled={busy}>
        <legend className={styles.legend}>Blood pressure (mmHg)</legend>
        <div className={styles.pair}>
          <label className={styles.field}>
            <span className={styles.fieldLabel}>Systolic</span>
            <input
              className={styles.input}
              inputMode="numeric"
              autoComplete="off"
              placeholder={`${SYSTOLIC_BOUNDS.min}-${SYSTOLIC_BOUNDS.max}`}
              value={draft.systolic}
              aria-invalid={problems.systolic !== undefined || problems.pair !== undefined}
              onChange={(e) => onChange({ ...draft, systolic: e.target.value })}
            />
          </label>
          <span className={styles.slash} aria-hidden="true">
            /
          </span>
          <label className={styles.field}>
            <span className={styles.fieldLabel}>Diastolic</span>
            <input
              className={styles.input}
              inputMode="numeric"
              autoComplete="off"
              placeholder={`${DIASTOLIC_BOUNDS.min}-${DIASTOLIC_BOUNDS.max}`}
              value={draft.diastolic}
              aria-invalid={problems.diastolic !== undefined || problems.pair !== undefined}
              onChange={(e) => onChange({ ...draft, diastolic: e.target.value })}
            />
          </label>
        </div>
        {[problems.systolic, problems.diastolic, problems.pair].map(
          (text) =>
            text !== undefined && (
              <p key={text} className={styles.problem}>
                {text}
              </p>
            ),
        )}
      </fieldset>

      <fieldset className={styles.group} disabled={busy}>
        <legend className={styles.legend}>Level of consciousness (ACVPU)</legend>
        <div className={styles.choices}>
          <Choice
            name={group("acvpu")}
            checked={draft.acvpu === ""}
            label="Not recorded"
            onPick={() => onChange({ ...draft, acvpu: "" })}
          />
          {ACVPU_CHOICES.map((c) => (
            <Choice
              key={c.value}
              name={group("acvpu")}
              checked={draft.acvpu === c.value}
              label={`${c.value} ${c.label}`}
              onPick={() => onChange({ ...draft, acvpu: c.value })}
            />
          ))}
        </div>
      </fieldset>

      <fieldset className={styles.group} disabled={busy}>
        <legend className={styles.legend}>Oxygen</legend>
        <div className={styles.choices}>
          <Choice
            name={group("oxygen")}
            checked={draft.oxygen === ""}
            label="Not recorded"
            onPick={() => onChange({ ...draft, oxygen: "" })}
          />
          <Choice
            name={group("oxygen")}
            checked={draft.oxygen === "air"}
            label="Room air"
            onPick={() => onChange({ ...draft, oxygen: "air" })}
          />
          <Choice
            name={group("oxygen")}
            checked={draft.oxygen === "oxygen"}
            label="On supplemental oxygen"
            onPick={() => onChange({ ...draft, oxygen: "oxygen" })}
          />
        </div>
      </fieldset>

      <fieldset className={styles.group} disabled={busy}>
        <legend className={styles.legend}>SpO2 scale</legend>
        <div className={styles.choices}>
          <Choice
            name={group("scale")}
            checked={draft.spo2Scale === ""}
            label="Not recorded"
            onPick={() => onChange({ ...draft, spo2Scale: "" })}
          />
          <Choice
            name={group("scale")}
            checked={draft.spo2Scale === "1"}
            label="Scale 1"
            onPick={() => onChange({ ...draft, spo2Scale: "1" })}
          />
          <Choice
            name={group("scale")}
            checked={draft.spo2Scale === "2"}
            label="Scale 2"
            onPick={() => onChange({ ...draft, spo2Scale: "2" })}
          />
        </div>
        <p className={styles.hint}>
          Scale 2 is a clinician&rsquo;s decision (hypercapnic respiratory failure). It is never
          assumed.
        </p>
      </fieldset>

      <div className={styles.echo} aria-live="polite">
        {echo.length > 0 ? (
          <>
            <p className={styles.echoTitle}>
              Will be recorded as a manual entry by {clinicianId}:
            </p>
            <ul className={styles.echoList}>
              {echo.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </>
        ) : (
          <p className={styles.echoTitle}>Nothing to record yet.</p>
        )}
      </div>

      {problems.form !== undefined && (
        <p className={styles.problem} role="alert">
          {problems.form}
        </p>
      )}
      {failure !== null && (
        <p className={styles.failure} role="alert">
          {failure}
        </p>
      )}
      {standingText !== null && (
        <p className={styles.standing} role="status">
          {standingText}
        </p>
      )}

      <div className={styles.actions}>
        <button type="submit" className={styles.primary} disabled={busy}>
          {busy ? "Recording…" : "Record"}
        </button>
        <button type="button" className={styles.secondary} onClick={onClose}>
          Close
        </button>
      </div>
    </form>
  );
}

function Choice(props: {
  readonly name: string;
  readonly checked: boolean;
  readonly label: string;
  readonly onPick: () => void;
}) {
  return (
    <label className={styles.choice}>
      <input type="radio" name={props.name} checked={props.checked} onChange={props.onPick} />
      <span>{props.label}</span>
    </label>
  );
}

// --- Behaviour: the draft, the request, and what came back ---

interface Props {
  readonly patientId: string;
  readonly patientName: string;
  readonly clinicianId: string;
  readonly onRecorded: (recorded: VitalsRecorded) => void;
  readonly onClose: () => void;
}

export function VitalsEntry({ patientId, patientName, clinicianId, onRecorded, onClose }: Props) {
  const [draft, setDraft] = useState<VitalsDraft>(EMPTY_DRAFT);
  const [problems, setProblems] = useState<DraftProblems>({});
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [standingText, setStandingText] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setFailure(null);
    setStandingText(null);
    const outcome = await submitDraft(patientId, draft, recordVitals);
    setBusy(false);
    if (outcome.kind === "invalid") {
      setProblems(outcome.problems);
    } else if (outcome.kind === "failed") {
      setProblems({});
      setFailure(outcome.message);
    } else {
      setProblems({});
      setDraft(EMPTY_DRAFT);
      setStandingText(standing(outcome.recorded));
      onRecorded(outcome.recorded);
    }
  };

  return (
    <VitalsEntryForm
      patientId={patientId}
      patientName={patientName}
      clinicianId={clinicianId}
      draft={draft}
      problems={problems}
      busy={busy}
      failure={failure}
      standingText={standingText}
      onChange={(next) => {
        setDraft(next);
        setProblems({});
      }}
      onSubmit={() => void submit()}
      onClose={onClose}
    />
  );
}
