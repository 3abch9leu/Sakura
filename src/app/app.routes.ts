import { Routes } from '@angular/router';
import { HomeComponent } from './home/home';
import { DesignComponent } from './design/design';
import { LoginComponent } from './login/login';
import { EnergyComponent } from './energy/energy';
import { SpaceComponent } from './space/space';

export const routes: Routes = [
  { path: '', component: HomeComponent, title: 'InBetween' },
  { path: 'design', component: DesignComponent, title: 'Design your screen · InBetween' },
  { path: 'space', component: SpaceComponent, title: 'Your space · InBetween' },
  { path: 'energy', component: EnergyComponent, title: 'Energy & Comfort · InBetween' },
  { path: 'login', component: LoginComponent, title: 'Sign in · InBetween' },
  { path: '**', redirectTo: '' },
];
