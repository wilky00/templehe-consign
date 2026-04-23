# Normalized App Field Schema v1

This schema is designed for an appraisal app that starts with common intake fields and then branches by equipment category.

## Core Intake Fields

- **appraisal_id**: `string`, required=true — Unique appraisal record ID
- **appraisal_date**: `date`, required=true — Date of site visit
- **appraiser_name**: `string`, required=true — Field tech/appraiser name
- **customer_name**: `string`, required=true — Owner or seller
- **customer_contact**: `string`, required=false — Primary contact details
- **site_name**: `string`, required=false — Jobsite, yard, or farm name
- **site_address**: `string`, required=true — Inspection location
- **asset_category**: `enum`, required=true — Machine category selected from master list
- **make**: `string`, required=true — Manufacturer
- **model**: `string`, required=true — Model designation
- **serial_number**: `string`, required=true — Serial or PIN
- **year**: `integer`, required=false — Model year if confirmed
- **hours_meter**: `decimal`, required=true — Displayed operating hours
- **hours_verified**: `boolean`, required=true — Whether meter believed accurate
- **ownership_type**: `enum`, required=true — Owned, financed, leased, unknown
- **lien_status**: `enum`, required=false — Clear, lien reported, unknown
- **acquisition_path**: `enum`, required=true — Consignment or direct purchase candidate
- **running_status**: `enum`, required=true — Running, partial, non-running
- **can_cold_start**: `boolean`, required=true — Was cold start observed
- **emissions_tier**: `enum`, required=false — Tier/Stage label if visible
- **cab_type**: `enum`, required=true — Open station, canopy, enclosed cab
- **rops_present**: `boolean`, required=true — ROPS/FOPS present if applicable
- **transport_notes**: `text`, required=false — Only key issues affecting pickup to yard
- **service_records_available**: `boolean`, required=true — Maintenance records available
- **major_rebuild_history**: `text`, required=false — Engine, transmission, hydraulic, UC rebuilds
- **overall_cosmetic_condition**: `enum`, required=true — Excellent/Good/Fair/Poor/Inoperable/Not Verified
- **marketability_rating**: `enum`, required=true — Fast sell, average, slow sell, salvage risk
- **photo_set_complete**: `boolean`, required=true — Required photos captured
- **listing_notes**: `text`, required=false — Market-facing descriptive notes
- **red_flags_summary**: `text`, required=false — Major issues affecting value or listing

## Category Branches

### Articulated Dump Trucks
**Major components**
- Engine
- Transmission
- Center hitch/articulation
- Hydraulic system
- Axles/differentials
- Tires
- Cab/interior
- Body/chassis
**Inspection prompts**
- Cold start
- Exhaust smoke
- Fluid leaks
- Transmission shift quality
- Center hitch play
- Body floor wear
- Cylinder leakage
- Tire matching
- Brake performance
- Cab electronics
**Attachments/options**
- Tailgate
- Body liner
- Heated body
- Payload weighing system
- Camera system
- Fire suppression
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab interior
- Engine compartment
- Center hitch close-up
- All tires
- Dump body floor
- Visible leaks/damage

### Rigid Frame Dump Trucks
**Major components**
- Engine
- Transmission
- Hydraulic hoist
- Axles/suspension
- Frame/chassis
- Tires
- Cab/interior
- Body
**Inspection prompts**
- Cold start
- Frame cracks
- Body floor wear
- Cylinder leakage
- Steering play
- Brake performance
- Tire matching
- Transmission operation
- Suspension condition
- Cab electronics
**Attachments/options**
- Tailgate
- Body liner
- Canopy
- Camera system
- Payload system
- Fire suppression
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab interior
- Engine compartment
- Frame rails
- All tires
- Dump body floor
- Visible leaks/damage

### Backhoe Loaders
**Major components**
- Engine
- Transmission/driveline
- Loader assembly
- Backhoe assembly
- Hydraulic system
- Pins/bushings
- Tires
- Cab/controls
**Inspection prompts**
- Cold start
- Hydraulic drift
- Stabilizer hold
- Swing frame wear
- Boom/stick welds
- Pin looseness
- Bucket cutting edge
- 4WD engagement
- Tire condition
- Cab controls
**Attachments/options**
- General purpose bucket
- 4-in-1 bucket
- Extendahoe
- Quick coupler
- Forks
- Hydraulic hammer circuit
- Thumb
- Auger
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab or operator station
- Engine compartment
- Loader bucket edge
- Backhoe bucket teeth
- Outriggers
- Tires
- Visible leaks/damage

### Dozers
**Major components**
- Engine
- Transmission/steering
- Final drives
- Undercarriage
- Blade assembly
- Ripper assembly
- Hydraulic system
- Cab/controls
**Inspection prompts**
- Cold start
- Blow-by
- Undercarriage wear
- Final drive noise/leaks
- Blade push arm wear
- Trunnion wear
- Ripper frame wear
- Steering response
- Hydraulic leaks
- Cab/AC condition
**Attachments/options**
- PAT blade
- SU blade
- U blade
- Winch
- Single shank ripper
- Multi-shank ripper
- Sweeps
- Rear screen
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab interior
- Engine compartment
- Both track sides
- Sprockets/idlers/rollers
- Blade cutting edge
- Ripper
- Visible leaks/damage

### Excavators
**Major components**
- Engine
- Hydraulic pumps/system
- Swing system
- Boom/stick/bucket
- Undercarriage
- Travel motors/drives
- Cab/controls
- Attachments
**Inspection prompts**
- Cold start
- Hydraulic response
- Swing bearing play
- Swing brake hold
- Boom/stick cracks
- Pin/bushing wear
- Track wear
- Travel motor performance
- Cab electronics
- Aux hydraulic function
**Attachments/options**
- General purpose bucket
- Ditch bucket
- Hydraulic thumb
- Coupler
- Hammer
- Grapple
- Mulcher head
- Tilt bucket
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab interior
- Engine compartment
- Boom base
- Stick and bucket
- Coupler/thumb
- Undercarriage both sides
- Visible leaks/damage

### Mini Excavators
**Major components**
- Engine
- Hydraulic system
- Swing system
- Boom/stick/bucket
- Tracks/undercarriage
- Blade
- Cab/controls
- Attachments
**Inspection prompts**
- Cold start
- Hydraulic drift
- Swing play
- Track wear
- Blade cylinder leakage
- Boom/stick welds
- Pins/bushings
- Travel function
- Cab/canopy condition
- Aux hydraulic operation
**Attachments/options**
- Bucket set
- Thumb
- Coupler
- Auger drive
- Breaker
- Grapple
- Tilt bucket
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Operator station
- Engine compartment
- Bucket and thumb
- Blade
- Tracks both sides
- Visible leaks/damage

### Wheel Loaders
**Major components**
- Engine
- Transmission
- Hydraulics
- Articulation/frame
- Axles
- Tires
- Loader arms/bucket
- Cab/controls
**Inspection prompts**
- Cold start
- Center pin play
- Boom arm cracks
- Bucket edge wear
- Lift drift
- Transmission shift quality
- Axle leakage
- Tire matching
- Brake performance
- Cab electronics
**Attachments/options**
- General purpose bucket
- Forks
- Quick coupler
- High lift arms
- Scale system
- Snow pusher
- Grapple bucket
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab interior
- Engine compartment
- Center articulation
- Bucket edge
- All tires
- Visible leaks/damage

### Skid Steers
**Major components**
- Engine
- Hydraulic system
- Drive system
- Lift arms/frame
- Tires
- Cab/controls
- Quick attach
- Attachments
**Inspection prompts**
- Cold start
- Hydraulic response
- Drive straightness
- Chain case noise
- Lift arm play
- Quick attach wear
- Tire wear
- Cab door/glass
- Seat bar/safety interlocks
- Aux function
**Attachments/options**
- General purpose bucket
- Forks
- Auger
- Grapple
- Trencher
- Cold planer
- Broom
- Breaker
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab interior
- Engine compartment
- Quick attach
- Bucket cutting edge
- All tires
- Visible leaks/damage

### Compact Track Loaders
**Major components**
- Engine
- Hydraulic system
- Drive system
- Tracks/undercarriage
- Lift arms/frame
- Cab/controls
- Quick attach
- Attachments
**Inspection prompts**
- Cold start
- Hydraulic response
- Track wear
- Sprocket/roller wear
- Lift arm play
- Quick attach wear
- Drive performance
- Cab condition
- High-flow function
- Leaks/damage
**Attachments/options**
- General purpose bucket
- Forks
- Mulcher
- Brush cutter
- Auger
- Grapple
- Trencher
- Breaker
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab interior
- Engine compartment
- Quick attach
- Bucket cutting edge
- Tracks/rollers both sides
- Visible leaks/damage

### Motor Graders
**Major components**
- Engine
- Transmission
- Circle/drawbar/moldboard
- Articulation/steering
- Hydraulic system
- Axles/tandems
- Tires
- Cab/controls
**Inspection prompts**
- Cold start
- Circle wear
- Drawbar looseness
- Moldboard edge wear
- Articulation play
- Steering response
- Transmission operation
- Tandem leaks
- Hydraulic leaks
- Cab electronics/GPS
**Attachments/options**
- Front blade
- Scarifier
- Ripper
- Snow wing
- GPS mast kit
- Cross slope controls
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab interior
- Engine compartment
- Circle and drawbar
- Moldboard edge
- Tandems
- All tires
- Visible leaks/damage

### Telehandlers
**Major components**
- Engine
- Transmission
- Boom assembly
- Hydraulic system
- Axles/steering
- Tires
- Cab/controls
- Attachments/stabilizers
**Inspection prompts**
- Cold start
- Boom section wear
- Boom extend/retract smoothness
- Frame leveling operation
- Stabilizer function
- Hydraulic leaks
- Tire wear
- Brake performance
- Attachment lock-up
- Cab condition
**Attachments/options**
- Fork carriage
- Bucket
- Jib
- Winch
- Personnel basket
- Truss boom
- Work lights
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab interior
- Engine compartment
- Boom wear pads
- Fork carriage or bucket
- Tires
- Outriggers
- Visible leaks/damage

### Wheel / Ag Tractors
**Major components**
- Engine
- Transmission/driveline
- PTO/3-point
- Hydraulic system
- Axles
- Tires
- Loader assembly
- Cab/controls
**Inspection prompts**
- Cold start
- PTO engagement
- 3-point lift hold
- Hydraulic remotes
- Transmission operation
- Front axle MFWD
- Tire condition
- Cab electronics
- Loader pin wear
- Leaks/damage
**Attachments/options**
- Loader
- Bucket
- Forks
- Rear remotes
- Ballast
- Quick hitch
- Guidance components
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab or operator station
- Engine compartment
- Rear PTO/3-point
- Loader and bucket
- All tires
- Visible leaks/damage

### Crawler Loaders
**Major components**
- Engine
- Transmission/steering
- Final drives
- Undercarriage
- Loader assembly
- Hydraulic system
- Cab/controls
- Bucket/attachments
**Inspection prompts**
- Cold start
- Undercarriage wear
- Final drive noise/leaks
- Loader arm cracks
- Bucket wear
- Lift drift
- Steering response
- Hydraulic leaks
- Cab condition
- Visible repairs
**Attachments/options**
- General purpose bucket
- Multi-purpose bucket
- Forks
- Ripper
- Winch
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab or operator station
- Engine compartment
- Bucket edge
- Both track sides
- Sprockets/idlers/rollers
- Visible leaks/damage

### Scrapers
**Major components**
- Engine
- Transmission
- Bowl/apron/ejector
- Hydraulic system
- Frame/gooseneck
- Axles
- Tires
- Cab/controls
**Inspection prompts**
- Cold start
- Transmission operation
- Bowl floor wear
- Cutting edge wear
- Apron cylinders
- Ejector movement
- Gooseneck/frame cracking
- Axle leaks
- Tire wear
- Cab electronics
**Attachments/options**
- Push block
- Cushion hitch
- Heaped bowl
- Automatic controls
- Camera system
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab interior
- Engine compartment
- Bowl floor
- Cutting edge
- Gooseneck/frame
- All tires
- Visible leaks/damage

### Rollers / Compactors
**Major components**
- Engine
- Drive system
- Drum/vibration
- Articulation/frame
- Water system
- Tires if applicable
- Cab/controls
- Attachments
**Inspection prompts**
- Cold start
- Vibration operation
- Drum shell damage
- Articulation play
- Hydrostatic response
- Water spray function
- Tire wear if equipped
- Cab/ROPS condition
- Leaks/damage
- Meter/controls
**Attachments/options**
- Padfoot shell kit
- Blade
- Cab package
- Edge cutters
- Work lights
**Required photos**
- 4 corner exterior
- Serial plate
- Hour meter
- Cab or operator station
- Engine compartment
- Drum(s) close-up
- Articulation
- Tires if applicable
- Visible leaks/damage
