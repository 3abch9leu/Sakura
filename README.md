# Sakura

This project was generated using [Angular CLI](https://github.com/angular/angular-cli) version 21.2.24.

## Development server

To start a local development server, run:

```bash
ng serve
```

Once the server is running, open your browser and navigate to `http://localhost:4200/`. The application will automatically reload whenever you modify any of the source files.

## Code scaffolding

Angular CLI includes powerful code scaffolding tools. To generate a new component, run:

```bash
ng generate component component-name
```

For a complete list of available schematics (such as `components`, `directives`, or `pipes`), run:

```bash
ng generate --help
```

## Building

To build the project run:

```bash
ng build
```

This will compile your project and store the build artifacts in the `dist/` directory. By default, the production build optimizes your application for performance and speed.

## Running unit tests

To execute unit tests with the [Vitest](https://vitest.dev/) test runner, use the following command:

```bash
ng test
```

## Running end-to-end tests

For end-to-end (e2e) testing, run:

```bash
ng e2e
```

Angular CLI does not come with an end-to-end testing framework by default. You can choose one that suits your needs.

## Additional Resources

For more information on using the Angular CLI, including detailed command references, visit the [Angular CLI Overview and Command Reference](https://angular.dev/tools/cli) page.

## Branch `final`: the complete INBETWEEN platform

This branch contains the whole working project:

- **Frontend** (this folder, Angular): landing page, design studio with the photo-like preview, digital twin,
  plant health, plant camera and live gallery, AI weather & climate, water quality, STEG energy companion,
  scenarios map, and the InBetween chat assistant (text + voice).
- **Backend** (`backend/`, FastAPI): `uvicorn api:app --port 8000` from `backend/` after `pip install -r requirements.txt`.

Integrated team branches: `chatbot` (assistant + voice relay in `server/`), `weather_prediction`
(model in `backend/rootcode/models/hweh-446k`, routes under `/api/weather`, `/api/iot`, `/api/climate`,
ESP32 firmware in `backend/arduino/esp32-inbetween`), `water_monitoring` (`public/water-monitor/`) and the
plant gallery and map from `front`.

Not in git (too large or secret):
- `backend/rootcode/models/deeplabv3_model.pth` (168 MB, leaf disease model): copy it there by hand.
- `backend/.env` and `server/.env`: API keys stay local (see `server/.env.example`).

Run: `npm install && ng serve` (site on http://localhost:4200), the API on port 8000, and optionally
`npm run voice:setup` then `npm run voice:server` for the live assistant.
