import { Routes } from '@angular/router';
import { HomeComponent } from './home/home';
import { DesignComponent } from './design/design';
import { LoginComponent } from './login/login';
import { EnergyComponent } from './energy/energy';

export const routes: Routes = [
  { path: '', component: HomeComponent, title: 'InBetween' },
  { path: 'design', component: DesignComponent, title: 'Design your screen · InBetween' },
  { path: 'energy', component: EnergyComponent, title: 'Energy & Comfort · InBetween' },
  { path: 'login', component: LoginComponent, title: 'Sign in · InBetween' },
  { path: '**', redirectTo: '' },
];
