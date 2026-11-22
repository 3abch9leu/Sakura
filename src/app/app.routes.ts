import { Routes } from '@angular/router';
import { HomeComponent } from './home/home';
import { DesignComponent } from './design/design';
import { LoginComponent } from './login/login';
import { EnergyComponent } from './energy/energy';
import { SpaceComponent } from './space/space';

export const routes: Routes = [
  { path: '', component: HomeComponent, title: 'InBetween' },
  { path: 'space', component: SpaceComponent, title: 'Your space · InBetween' },
  { path: 'studio', loadComponent: () => import('./studio/studio').then((m) => m.StudioComponent), title: 'Design studio · InBetween' },
  { path: 'dashboard', loadComponent: () => import('./dashboard/dashboard').then((m) => m.DashboardComponent), title: 'Digital twin · InBetween' },
  { path: 'plant-health', loadComponent: () => import('./plant-health/plant-health').then((m) => m.PlantHealthComponent), title: 'Plant health · InBetween' },
  { path: 'camera', loadComponent: () => import('./camera/camera').then((m) => m.CameraComponent), title: 'Plant camera · InBetween' },
  { path: 'weather', loadComponent: () => import('./weather/weather').then((m) => m.WeatherComponent), title: 'Weather & climate · InBetween' },
  { path: 'water-quality', loadComponent: () => import('./water-quality/water-quality').then((m) => m.WaterQualityComponent), title: 'Water quality · InBetween' },
  { path: 'gallery', loadComponent: () => import('./plant.component/plant.component').then((m) => m.PlantComponent), title: 'Plant gallery · InBetween' },
  { path: 'map', loadComponent: () => import('./tunisia-map/tunisia-map').then((m) => m.TunisiaMapComponent), title: 'Scenarios map · InBetween' },
  { path: 'design', component: DesignComponent, title: 'Quick window design · InBetween' },
  { path: 'energy', component: EnergyComponent, title: 'Energy & Comfort · InBetween' },
  { path: 'login', component: LoginComponent, title: 'Sign in · InBetween' },
  { path: '**', redirectTo: '' },
];
