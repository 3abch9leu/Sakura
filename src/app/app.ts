import { Component, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { HomeComponent } from './home/home';
import { LoginComponent } from './login/login';
import {  } from './login/login';
import { DesignComponent } from './design/design';
import { SpaceComponent } from './space/space';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, HomeComponent, LoginComponent, DesignComponent, SpaceComponent],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  protected readonly title = signal('sakura');
}
