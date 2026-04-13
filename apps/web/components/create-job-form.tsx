"use client";

import { CreateImageRequest, AspectRatioPreset } from "@image-platform/shared";
import { useRouter } from "next/navigation";
import { startTransition, useState } from "react";

import { createImageJob } from "@/lib/api";

const aspectRatios: AspectRatioPreset[] = ["1:1", "16:9", "9:16", "4:5", "3:2"];

export function CreateJobForm() {
  const router = useRouter();
  const [form, setForm] = useState<CreateImageRequest>({
    prompt: "",
    negative_prompt: "",
    aspect_ratio: "1:1",
    mode: "photoreal",
    auto_enhance_prompt: false,
  });
  const [seed, setSeed] = useState("");
  const [inputFile, setInputFile] = useState<File | null>(null);
  const [inputStrength, setInputStrength] = useState("0.6");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      let inputPayload: Partial<CreateImageRequest> = {};
      if (inputFile) {
        const dataUrl = await readFileAsDataUrl(inputFile);
        const [, base64 = ""] = dataUrl.split(",", 2);
        inputPayload = {
          input_image_base64: base64,
          input_image_mime_type: inputFile.type || "image/png",
          input_image_strength: Number(inputStrength),
        };
      }
      const payload: CreateImageRequest = {
        ...form,
        seed: seed.trim() ? Number(seed.trim()) : undefined,
        ...inputPayload,
      };
      const job = await createImageJob(payload);
      startTransition(() => router.push(`/images/${job.id}`));
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Unable to create the job.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className="form-grid" onSubmit={handleSubmit}>
      <div className="field">
        <label htmlFor="prompt">Prompt</label>
        <textarea
          id="prompt"
          className="textarea"
          placeholder="Describe the image like a realistic photograph with subject, lens, light, styling, and scene."
          value={form.prompt}
          onChange={(event) => setForm((current) => ({ ...current, prompt: event.target.value }))}
          required
        />
      </div>

      <div className="field">
        <label htmlFor="negative_prompt">Negative prompt</label>
        <textarea
          id="negative_prompt"
          className="textarea"
          placeholder="Optional exclusions, artifacts, or style constraints."
          value={form.negative_prompt ?? ""}
          onChange={(event) => setForm((current) => ({ ...current, negative_prompt: event.target.value }))}
        />
      </div>

      <div className="field">
        <label>Aspect ratio</label>
        <div className="segmented">
          {aspectRatios.map((ratio) => (
            <button
              key={ratio}
              type="button"
              data-active={form.aspect_ratio === ratio}
              onClick={() => setForm((current) => ({ ...current, aspect_ratio: ratio }))}
            >
              {ratio}
            </button>
          ))}
        </div>
      </div>

      <div className="field">
        <label htmlFor="seed">Seed</label>
        <input
          id="seed"
          className="input mono"
          inputMode="numeric"
          placeholder="Optional deterministic seed"
          value={seed}
          onChange={(event) => setSeed(event.target.value.replace(/[^0-9]/g, ""))}
        />
      </div>

      <div className="field">
        <label htmlFor="input_image">Reference image</label>
        <input
          id="input_image"
          className="input"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          onChange={(event) => setInputFile(event.target.files?.[0] ?? null)}
        />
        <div className="section-subtitle">Optional. Sends one source image and switches generation to image-to-image.</div>
      </div>

      <div className="field">
        <label htmlFor="input_strength">Reference strength</label>
        <input
          id="input_strength"
          className="input mono"
          inputMode="decimal"
          placeholder="0.6"
          value={inputStrength}
          onChange={(event) => setInputStrength(event.target.value)}
          disabled={!inputFile}
        />
      </div>

      <label className="field" style={{ gridTemplateColumns: "auto 1fr", alignItems: "center", gap: 12 }}>
        <input
          type="checkbox"
          checked={Boolean(form.auto_enhance_prompt)}
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              auto_enhance_prompt: event.target.checked,
            }))
          }
        />
        <span>
          Auto enhance prompt
          <div className="section-subtitle">Exposed now, disabled by default in the backend until PromptEnhancer is enabled.</div>
        </span>
      </label>

      {error ? <div className="error">{error}</div> : null}

      <button className="button" type="submit" disabled={isSubmitting || !form.prompt.trim()}>
        {isSubmitting ? "Queueing image..." : "Generate image"}
      </button>
    </form>
  );
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("Unable to read the selected file."));
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.readAsDataURL(file);
  });
}
