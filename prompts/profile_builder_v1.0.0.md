# Profile Builder Prompt — v1.0.0

You are extracting a structured Screening Profile from program documents. The profile will be used by a rules engine and a model-assisted analysis pipeline to screen applicants for a demanding program.

Your task: read the provided documents and extract all screening-relevant information into the JSON schema below. Be thorough and precise:

1. **Hard criteria (exclusionary):** Extract every condition, medication, or circumstance the documents say should exclude an applicant. Preserve the document's criterion IDs exactly (e.g., A1, A2). Include detection hints: what checklist fields, medication names, or keywords in an intake form would indicate this criterion applies, and which form sections to search.

2. **Caution criteria:** Extract every condition requiring follow-up before clearance. Same ID preservation and detection hints.

3. **Medication classes of concern:** Extract each medication class mentioned, with example drug names, why it matters for this program, and the criterion it relates to.

4. **Program demands:** Extract specific physical, psychological, dietary, or environmental demands that interact with applicant health. For each, note which intake form sections it interacts with.

5. **Positive indicators:** Extract what the documents describe as green flags or positive signs.

6. **Ground rules:** Extract any absolute behavioral rules for the screening system (e.g., "never advise medication changes"). These are constraints on how the system operates, not criteria about applicants.

Be conservative: if a document says something is exclusionary, mark it as hard. If it says "follow-up required," mark it as caution. Preserve the source document's language in excerpts.

## Response Schema

Respond with a JSON object matching this schema:

```json
{
  "type": "object",
  "properties": {
    "hard_criteria": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {"type": "string"},
          "description": {"type": "string"},
          "detection": {
            "type": "object",
            "properties": {
              "checklist_fields": {"type": "array", "items": {"type": "string"}},
              "keywords": {"type": "array", "items": {"type": "string"}},
              "medication_names": {"type": "array", "items": {"type": "string"}},
              "sections": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["checklist_fields", "keywords", "medication_names", "sections"]
          },
          "source_doc": {"type": "string"},
          "source_excerpt": {"type": "string"}
        },
        "required": ["id", "description", "detection", "source_doc", "source_excerpt"]
      }
    },
    "caution_criteria": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {"type": "string"},
          "description": {"type": "string"},
          "detection": {
            "type": "object",
            "properties": {
              "checklist_fields": {"type": "array", "items": {"type": "string"}},
              "keywords": {"type": "array", "items": {"type": "string"}},
              "medication_names": {"type": "array", "items": {"type": "string"}},
              "sections": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["checklist_fields", "keywords", "medication_names", "sections"]
          },
          "source_doc": {"type": "string"},
          "source_excerpt": {"type": "string"}
        },
        "required": ["id", "description", "detection", "source_doc", "source_excerpt"]
      }
    },
    "medication_classes_of_concern": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "class_name": {"type": "string"},
          "example_names": {"type": "array", "items": {"type": "string"}},
          "why": {"type": "string"},
          "criterion_ref": {"type": "string"},
          "source_doc": {"type": "string"}
        },
        "required": ["class_name", "example_names", "why", "criterion_ref", "source_doc"]
      }
    },
    "program_demands": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {"type": "string"},
          "demand": {"type": "string"},
          "interacts_with": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["id", "demand", "interacts_with"]
      }
    },
    "positive_indicators": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {"type": "string"},
          "description": {"type": "string"}
        },
        "required": ["id", "description"]
      }
    },
    "ground_rules": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "rule": {"type": "string"},
          "source_doc": {"type": "string"}
        },
        "required": ["rule", "source_doc"]
      }
    }
  },
  "required": ["hard_criteria", "caution_criteria", "medication_classes_of_concern", "program_demands", "positive_indicators", "ground_rules"]
}
```
