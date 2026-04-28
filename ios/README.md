# TempleHE Appraiser — iOS

SwiftUI app for field appraisers. iOS 16+ deployment target. Phase 5 Sprint 0
shipped this scaffold; subsequent sprints layer on auth, dashboard, dynamic
form, photo capture, and offline sync (see `dev_plan/05_phase5_ios_app.md`).

## Prerequisites

- **Xcode 15.4+** — confirm with `xcodebuild -version`. The project targets
  iOS 16 but uses SwiftUI features available in the 15.4 toolchain.
- **XcodeGen** — generates `TempleHEAppraiser.xcodeproj` from the version-
  controlled `project.yml`. Install with Homebrew:
  ```sh
  brew install xcodegen
  ```
- **iOS Simulator** — at least one iPhone or iPad simulator runtime
  installed via Xcode → Settings → Platforms.

## First-time setup

```sh
cd ios
xcodegen generate              # produces TempleHEAppraiser.xcodeproj
open TempleHEAppraiser.xcodeproj
```

In Xcode, set your development team under
**TempleHEAppraiser → Signing & Capabilities → Team**. The bundle ID
(`com.templehe.appraiser`) is fixed in `project.yml`; teams are local-
only and never checked in.

## Building

```sh
cd ios
xcodebuild build \
  -scheme TempleHEAppraiser \
  -destination 'platform=iOS Simulator,name=iPhone 15 Pro,OS=latest'
```

Or hit ⌘R in Xcode after picking a simulator.

## Testing

Local unit + UI tests (no GitHub Actions runner; iOS CI is deferred per
ADR-021 cost analysis):

```sh
cd ios
xcodebuild test \
  -scheme TempleHEAppraiser \
  -destination 'platform=iOS Simulator,name=iPhone 15 Pro,OS=latest'
```

Or hit ⌘U in Xcode.

## Project layout

```
ios/
├── project.yml                         # XcodeGen spec (source of truth)
├── TempleHEAppraiser/                  # main app target
│   ├── App.swift                       # @main entry
│   ├── RootView.swift                  # tab bar
│   ├── Info.plist
│   └── Assets.xcassets/
├── TempleHEAppraiserTests/             # XCTest unit tests
└── TempleHEAppraiserUITests/           # XCUITest UI tests
```

The `.xcodeproj` is **not** version-controlled. Re-run `xcodegen generate`
after pulling changes to `project.yml`. This keeps PRs free of binary
project-file churn.

## Sprint roadmap (per `dev_plan/05_phase5_ios_app.md`)

| Sprint | Adds |
|---|---|
| 0 | Scaffold, tab bar stub, smoke tests *(done)* |
| 1 | Auth (email/pw + 2FA + biometric), Keychain, device-token registration |
| 2 | Dashboard, assignment cards, Maps deep-links, APNs receipt |
| 3 | Valuation lookup |
| 4 | Dynamic appraisal form + Core Data |
| 5 | Camera capture (live-only), EXIF, GPS radius validation |
| 6 | Offline sync via BGTaskScheduler |
| 7 | XCUITest gate, Sentry crash reporting, TestFlight |

## TestFlight

Sprint 7 will add a Fastlane lane for TestFlight upload. Until then,
distribution is local-build → archive → upload via Xcode Organizer.

## Notes

- Camera-only photo capture (no camera-roll) is enforced at the
  `UIImagePickerController` config level in Sprint 5; the `Info.plist`
  already declares `NSCameraUsageDescription`.
- The app talks to the existing TempleHE FastAPI backend at
  `https://api.templehe-staging.fly.dev` (Sprint 1 wires the client +
  base URL configuration).
- Push uses APNs **directly** — no Firebase / FCM. The backend signs
  JWTs against an Apple AuthKey loaded from the integration credentials
  vault. See ADR-021 for the rationale.
