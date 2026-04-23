# Core Intake Checklist

Use this checklist before branching into the machine-specific inspection. Required fields should be completed for every unit.

## Identity and Ownership

- **appraisal_id** (string, required): Unique appraisal record ID
- **appraisal_date** (date, required): Date of site visit
- **appraiser_name** (string, required): Field tech/appraiser name
- **customer_name** (string, required): Owner or seller
- **customer_contact** (string, optional): Primary contact details
- **site_name** (string, optional): Jobsite, yard, or farm name
- **site_address** (string, required): Inspection location
- **asset_category** (enum, required): Machine category selected from master list
- **make** (string, required): Manufacturer
- **model** (string, required): Model designation
- **serial_number** (string, required): Serial or PIN
- **year** (integer, optional): Model year if confirmed
- **hours_meter** (decimal, required): Displayed operating hours
- **hours_verified** (boolean, required): Whether meter believed accurate
- **ownership_type** (enum, required): Owned, financed, leased, unknown
- **lien_status** (enum, optional): Clear, lien reported, unknown
- **acquisition_path** (enum, required): Consignment or direct purchase candidate
- **running_status** (enum, required): Running, partial, non-running
- **can_cold_start** (boolean, required): Was cold start observed
- **emissions_tier** (enum, optional): Tier/Stage label if visible
- **cab_type** (enum, required): Open station, canopy, enclosed cab
- **rops_present** (boolean, required): ROPS/FOPS present if applicable
- **transport_notes** (text, optional): Only key issues affecting pickup to yard
- **service_records_available** (boolean, required): Maintenance records available
- **major_rebuild_history** (text, optional): Engine, transmission, hydraulic, UC rebuilds
- **overall_cosmetic_condition** (enum, required): Excellent/Good/Fair/Poor/Inoperable/Not Verified
- **marketability_rating** (enum, required): Fast sell, average, slow sell, salvage risk
- **photo_set_complete** (boolean, required): Required photos captured
- **listing_notes** (text, optional): Market-facing descriptive notes
- **red_flags_summary** (text, optional): Major issues affecting value or listing

## Required Photo Set
- 4-corner exterior
- Serial/PIN plate
- Hour meter
- Operator station or cab interior
- Engine compartment
- Visible leaks, damage, weld repairs, or missing guards


## Required Capture Rules
- Observe a true cold start when possible
- Record if hours appear unverifiable or changed
- Mark running status as running, partial, or non-running
- Note whether the unit is a consignment candidate, direct-buy candidate, or both
- Flag major rebuilds, structural damage, excessive leaks, and missing serial plate immediately
