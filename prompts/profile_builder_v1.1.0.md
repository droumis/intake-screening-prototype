# Profile Builder Prompt — v1.1.0

You are extracting a structured Screening Profile from program documents. The profile will be used by a rules engine and a model-assisted analysis pipeline to screen applicants for a demanding program.

Your task: read the provided documents and extract all screening-relevant information into the JSON schema below. Be thorough and precise:

1. **Hard criteria (exclusionary):** Extract every condition, medication, or circumstance the documents say should exclude an applicant (cannot proceed, no resolution pathway). Preserve the document's criterion IDs exactly (e.g., R-A1, H-1). Include detection hints: what checklist fields, medication names, or keywords in an intake form would indicate this criterion applies, and which form sections to search. Set `basis` to "regulatory" if the criterion comes from a law/rule section (Part 1, R- prefixed) or "house" if from the center's own standards (Part 2, H- prefixed). Set `citation` to the rule reference (e.g., "OAR 333-333-5050(3)(a)" or "4 CCR 755-1 Rule 2.2").

2. **Caution criteria:** Extract every condition requiring follow-up before clearance. Same ID preservation, detection hints, basis, and citation. Set `default_level` to "red" if the document describes the criterion as serious/red-level but resolvable (not exclusionary); leave as "yellow" for standard caution criteria. Set `resolution_pathway` to describe how the criterion can be resolved (e.g., "documented referral, clearance, or consultation per Rule 2.2; safety plan on heightened risk").

   **CRITICAL CLASSIFICATION RULE:** A criterion whose document says it is *not* exclusionary and defines a clearance/consultation pathway must NOT be classified as a hard criterion, whatever its severity. Represent it as a caution criterion with `default_level: "red"`. This applies even if the criterion involves medications (like lithium) that would be exclusionary under a different jurisdiction's rules. Read ONLY what THIS document says about the disposition.

3. **Medication classes of concern:** Extract each medication class mentioned, with example drug names, why it matters for this program, and the criterion it relates to.

4. **Program demands:** Extract specific physical, psychological, dietary, or environmental demands that interact with applicant health. For each, note which intake form sections it interacts with.

5. **Positive indicators:** Extract what the documents describe as green flags or positive signs.

6. **Ground rules:** Extract any absolute behavioral rules for the screening system (e.g., "never advise medication changes"). These are constraints on how the system operates, not criteria about applicants.

Be conservative: if a document says something is exclusionary, mark it as hard. If it says "follow-up required" or defines a clearance pathway, mark it as caution (with appropriate default_level). Preserve the source document's language in excerpts.

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
          "source_excerpt": {"type": "string"},
          "basis": {"type": "string", "enum": ["regulatory", "house"]},
          "citation": {"type": "string"}
        },
        "required": ["id", "description", "detection", "source_doc", "source_excerpt", "basis", "citation"]
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
          "source_excerpt": {"type": "string"},
          "default_level": {"type": "string", "enum": ["yellow", "red"]},
          "basis": {"type": "string", "enum": ["regulatory", "house"]},
          "citation": {"type": "string"},
          "resolution_pathway": {"type": "string"}
        },
        "required": ["id", "description", "detection", "source_doc", "source_excerpt", "default_level", "basis", "citation", "resolution_pathway"]
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
