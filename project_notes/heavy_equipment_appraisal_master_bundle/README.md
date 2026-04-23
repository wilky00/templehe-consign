# Heavy Equipment Appraisal Master Bundle

This bundle combines the original field checklist concept, the normalized app schema, the completed data dictionary, the implementation-ready CSV package, and an example appraiser journey for AFFiNE or any similar documentation/workflow tool.

## Folder Structure

- `01_checklists/`
  - Shared intake checklist
  - Condition scale and scoring guide
  - One markdown checklist per major equipment category
- `02_schema_and_dictionary/`
  - Normalized schema in markdown and JSON
  - Complete data dictionary CSV
- `03_implementation_package/`
  - App input fields only CSV
  - Reference tables CSV
  - Scoring and rules logic CSV
- `04_affine_journey_example/`
  - Markdown walkthrough
  - HTML visual flow
  - SVG flow diagram

## Recommended Use

1. Use the files in `01_checklists` to train field techs and standardize appraisal capture.
2. Use `02_schema_and_dictionary` as the master source for field names, data types, and category-specific logic.
3. Use `03_implementation_package` to build the actual app:
   - `04_app_input_fields_only.csv` for form fields
   - `05_reference_tables.csv` for dropdowns and lookup values
   - `06_scoring_and_rules_logic.csv` for weighted scoring, red-flag rules, and workflow logic
4. Use `04_affine_journey_example` to explain the future app flow to appraisers, product owners, and developers.

## Design Principles Used

- App-first structure
- Fast enough for a 30 to 45 minute field appraisal
- Strong focus on resale, cosmetics, marketability, and major value drivers
- Captures enough detail for both consignment and direct-buy decisions
- Supports running, partially running, and non-running equipment
- Includes required photos, attachments, scoring, and red flags

## Scoring Summary

Every category uses the same 0 to 5 condition scale definitions, but category weights vary by machine type.

Suggested overall score bands:
- 4.50 to 5.00: Premium resale-ready
- 3.75 to 4.49: Strong resale candidate
- 3.00 to 3.74: Usable with value deductions
- 2.00 to 2.99: Heavy discount / repair candidate
- 1.00 to 1.99: Project, salvage, or parts-biased
- 0.00 to 0.99: Not enough verified information

## Notes for Developers

- Shared intake fields should always be completed before category branching.
- Category-specific sections should appear only after asset category is selected.
- Required photos should be enforced by category.
- Red flags should trigger both an internal review notice and a marketability downgrade.
- Attachments should be stored as structured child records if possible.
- Scores should store both raw component scores and weighted overall score.

## Files Included

This package is self-contained and intended to replace the earlier fragmented bundles.
