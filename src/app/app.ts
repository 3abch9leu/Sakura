import { Component, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { HomeComponent } from './home/home';
import { LoginComponent } from './login/login';
import {  } from './login/login';
import { DesignComponent } from './design/design';
import { SpaceComponent } from './space/space';
import { PlantComponent } from './plant.component/plant.component';
import { ChatComponent } from './chat/chat';
import { TunisiaMapComponent } from './tunisia-map/tunisia-map';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, HomeComponent, LoginComponent, DesignComponent, SpaceComponent, PlantComponent, ChatComponent, TunisiaMapComponent],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  protected readonly title = signal('sakura');
}
